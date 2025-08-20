import numpy as np
import torch
import logging
import math
logger = logging.getLogger(__name__)

try:
    from nemo.collections.asr.models import SortformerEncLabelModel
except ImportError:
    raise SystemExit("""Please use `pip install "git+https://github.com/NVIDIA/NeMo.git@main#egg=nemo_toolkit[asr]"` to use the Sortformer diarization""")
    

diar_model = SortformerEncLabelModel.from_pretrained("nvidia/diar_streaming_sortformer_4spk-v2")
diar_model.eval()

if torch.cuda.is_available():
    diar_model.to(torch.device("cuda"))
    
# Set the streaming parameters corresponding to 1.04s latency setup. This will affect the streaming feat loader.
# diar_model.sortformer_modules.chunk_len = 6
# diar_model.sortformer_modules.spkcache_len = 188
# diar_model.sortformer_modules.chunk_right_context = 7
# diar_model.sortformer_modules.fifo_len = 188
# diar_model.sortformer_modules.spkcache_update_period = 144
# diar_model.sortformer_modules.log = False


# here we change the settings for our goal: speed!
# we want batches of around 1 second. one frame is 0.08s, so 1s is 12.5 frames. we take 12.
diar_model.sortformer_modules.chunk_len = 12

# for more speed, we reduce the 'right context'. it's like looking less into the future.
diar_model.sortformer_modules.chunk_right_context = 1

# we keep the rest same for now
diar_model.sortformer_modules.spkcache_len = 188
diar_model.sortformer_modules.fifo_len = 188
diar_model.sortformer_modules.spkcache_update_period = 144
diar_model.sortformer_modules.log = False
diar_model.sortformer_modules._check_streaming_parameters()

batch_size = 1
processed_signal_offset = torch.zeros((batch_size,), dtype=torch.long, device=diar_model.device)

# from nemo.collections.asr.parts.preprocessing.features import FilterbankFeatures
# from nemo.collections.asr.modules.audio_preprocessing import get_features
from nemo.collections.asr.modules.audio_preprocessing import AudioToMelSpectrogramPreprocessor


def prepare_audio_signal(signal):
    audio_signal = torch.tensor(signal).unsqueeze(0).to(diar_model.device)
    audio_signal_length = torch.tensor([audio_signal.shape[1]]).to(diar_model.device)
    processed_signal, processed_signal_length = AudioToMelSpectrogramPreprocessor(
            window_size= 0.025, 
            normalize="NA",
            n_fft=512,
            features=128).get_features(audio_signal, audio_signal_length)
    return processed_signal, processed_signal_length


def streaming_feat_loader(
    feat_seq, feat_seq_length, feat_seq_offset
):
    """
    Load a chunk of feature sequence for streaming inference.

    Args:
        feat_seq (torch.Tensor): Tensor containing feature sequence
            Shape: (batch_size, feat_dim, feat frame count)
        feat_seq_length (torch.Tensor): Tensor containing feature sequence lengths
            Shape: (batch_size,)
        feat_seq_offset (torch.Tensor): Tensor containing feature sequence offsets
            Shape: (batch_size,)

    Returns:
        chunk_idx (int): Index of the current chunk
        chunk_feat_seq (torch.Tensor): Tensor containing the chunk of feature sequence
            Shape: (batch_size, diar frame count, feat_dim)
        feat_lengths (torch.Tensor): Tensor containing lengths of the chunk of feature sequence
            Shape: (batch_size,)
    """
    feat_len = feat_seq.shape[2]
    num_chunks = math.ceil(feat_len / (diar_model.sortformer_modules.chunk_len * diar_model.sortformer_modules.subsampling_factor))
    if False:
        logging.info(
            f"feat_len={feat_len}, num_chunks={num_chunks}, "
            f"feat_seq_length={feat_seq_length}, feat_seq_offset={feat_seq_offset}"
        )

    stt_feat, end_feat, chunk_idx = 0, 0, 0
    while end_feat < feat_len:
        left_offset = min(diar_model.sortformer_modules.chunk_left_context * diar_model.sortformer_modules.subsampling_factor, stt_feat)
        end_feat = min(stt_feat + diar_model.sortformer_modules.chunk_len * diar_model.sortformer_modules.subsampling_factor, feat_len)
        right_offset = min(diar_model.sortformer_modules.chunk_right_context * diar_model.sortformer_modules.subsampling_factor, feat_len - end_feat)
        chunk_feat_seq = feat_seq[:, :, stt_feat - left_offset : end_feat + right_offset]
        feat_lengths = (feat_seq_length + feat_seq_offset - stt_feat + left_offset).clamp(
            0, chunk_feat_seq.shape[2]
        )
        feat_lengths = feat_lengths * (feat_seq_offset < end_feat)
        stt_feat = end_feat
        chunk_feat_seq_t = torch.transpose(chunk_feat_seq, 1, 2)
        if False:
            logging.info(
                f"chunk_idx: {chunk_idx}, "
                f"chunk_feat_seq_t shape: {chunk_feat_seq_t.shape}, "
                f"chunk_feat_lengths: {feat_lengths}"
            )
        yield chunk_idx, chunk_feat_seq_t, feat_lengths, left_offset, right_offset
        chunk_idx += 1


class StreamingSortformerState:
    """
    This class creates a class instance that will be used to store the state of the
    streaming Sortformer model.

    Attributes:
        spkcache (torch.Tensor): Speaker cache to store embeddings from start
        spkcache_lengths (torch.Tensor): Lengths of the speaker cache
        spkcache_preds (torch.Tensor): The speaker predictions for the speaker cache parts
        fifo (torch.Tensor): FIFO queue to save the embedding from the latest chunks
        fifo_lengths (torch.Tensor): Lengths of the FIFO queue
        fifo_preds (torch.Tensor): The speaker predictions for the FIFO queue parts
        spk_perm (torch.Tensor): Speaker permutation information for the speaker cache
        mean_sil_emb (torch.Tensor): Mean silence embedding
        n_sil_frames (torch.Tensor): Number of silence frames
    """

    spkcache = None  # Speaker cache to store embeddings from start
    spkcache_lengths = None  #
    spkcache_preds = None  # speaker cache predictions
    fifo = None  # to save the embedding from the latest chunks
    fifo_lengths = None
    fifo_preds = None
    spk_perm = None
    mean_sil_emb = None
    n_sil_frames = None


def init_streaming_state(self, batch_size: int = 1, async_streaming: bool = False, device: torch.device = None):
    """
    Initializes StreamingSortformerState with empty tensors or zero-valued tensors.

    Args:
        batch_size (int): Batch size for tensors in streaming state
        async_streaming (bool): True for asynchronous update, False for synchronous update
        device (torch.device): Device for tensors in streaming state

    Returns:
        streaming_state (SortformerStreamingState): initialized streaming state
    """
    streaming_state = StreamingSortformerState()
    if async_streaming:
        streaming_state.spkcache = torch.zeros((batch_size, self.spkcache_len, self.fc_d_model), device=device)
        streaming_state.spkcache_preds = torch.zeros((batch_size, self.spkcache_len, self.n_spk), device=device)
        streaming_state.spkcache_lengths = torch.zeros((batch_size,), dtype=torch.long, device=device)
        streaming_state.fifo = torch.zeros((batch_size, self.fifo_len, self.fc_d_model), device=device)
        streaming_state.fifo_lengths = torch.zeros((batch_size,), dtype=torch.long, device=device)
    else:
        streaming_state.spkcache = torch.zeros((batch_size, 0, self.fc_d_model), device=device)
        streaming_state.fifo = torch.zeros((batch_size, 0, self.fc_d_model), device=device)
    streaming_state.mean_sil_emb = torch.zeros((batch_size, self.fc_d_model), device=device)
    streaming_state.n_sil_frames = torch.zeros((batch_size,), dtype=torch.long, device=device)
    return streaming_state

def process_diarization(signal, chunks):
    
    audio_signal = torch.tensor(signal).unsqueeze(0).to(diar_model.device)
    audio_signal_length = torch.tensor([audio_signal.shape[1]]).to(diar_model.device)
    processed_signal, processed_signal_length = AudioToMelSpectrogramPreprocessor(
            window_size= 0.025, 
            normalize="NA",
            n_fft=512,
            features=128).get_features(audio_signal, audio_signal_length)

    
    streaming_loader = streaming_feat_loader(processed_signal, processed_signal_length, processed_signal_offset)

    
    streaming_state = init_streaming_state(diar_model.sortformer_modules,
        batch_size = batch_size,
        async_streaming = True,
        device = diar_model.device
    )
    total_preds = torch.zeros((batch_size, 0, diar_model.sortformer_modules.n_spk), device=diar_model.device)

    
    chunk_duration_seconds = diar_model.sortformer_modules.chunk_len * diar_model.sortformer_modules.subsampling_factor * diar_model.preprocessor._cfg.window_stride
    print(f"Chunk duration: {chunk_duration_seconds} seconds")

    l_speakers = [
        {'start_time': 0,
        'end_time': 0,
        'speaker': 0
        }
    ]
    len_prediction = None
    left_offset = 0
    right_offset = 8
    for i, chunk_feat_seq_t, _, _, _ in streaming_loader:
        with torch.inference_mode():
                streaming_state, total_preds = diar_model.forward_streaming_step(
                    processed_signal=chunk_feat_seq_t,
                    processed_signal_length=torch.tensor([chunk_feat_seq_t.shape[1]]),
                    streaming_state=streaming_state,
                    total_preds=total_preds,
                    left_offset=left_offset,
                    right_offset=right_offset,
                )
                left_offset = 8
                preds_np = total_preds[0].cpu().numpy()
                active_speakers = np.argmax(preds_np, axis=1)
                if len_prediction is None:
                    len_prediction = len(active_speakers) # we want to get the len of 1 prediction
                frame_duration = chunk_duration_seconds / len_prediction
                active_speakers = active_speakers[-len_prediction:]
                print(chunk_feat_seq_t.shape, total_preds.shape)
                for idx, spk in enumerate(active_speakers):
                    if spk != l_speakers[-1]['speaker']:
                        l_speakers.append(
                            {'start_time': i * chunk_duration_seconds + idx * frame_duration,
                            'end_time': i * chunk_duration_seconds + (idx + 1) * frame_duration,
                            'speaker': spk
                        })                    
                    else:
                        l_speakers[-1]['end_time'] = i * chunk_duration_seconds + (idx + 1) * frame_duration
                    
        print(l_speakers)
        """
        Should print
        [{'start_time': 0, 'end_time': 8.72, 'speaker': 0}, 
        {'start_time': 8.72, 'end_time': 18.88, 'speaker': 1},
        {'start_time': 18.88, 'end_time': 24.96, 'speaker': 2},
        {'start_time': 24.96, 'end_time': 31.68, 'speaker': 0}]
        """

if __name__ == '__main__':
    import librosa
    an4_audio = 'new_audio_test.mp3'
    signal, sr = librosa.load(an4_audio,sr=16000) 

    """
    ground truth:
    speaker 0 : 0:00 - 0:09
    speaker 1 : 0:09 - 0:19
    speaker 2 : 0:19 - 0:25
    speaker 0 : 0:25 - end
    """

    # Simulate streaming
    chunk_size = 16000  # 1 second
    chunks = []
    for i in range(0, len(signal), chunk_size):
        chunk = signal[i:i+chunk_size]
        chunks.append(chunk)

    process_diarization(signal, chunks)