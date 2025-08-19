import numpy as np
import torch
import logging
from whisperlivekit.timed_objects import SpeakerSegment

logger = logging.getLogger(__name__)

try:
    from nemo.collections.asr.models import SortformerEncLabelModel
except ImportError:
    raise SystemExit("""Please use `pip install "git+https://github.com/NVIDIA/NeMo.git@main#egg=nemo_toolkit[asr]"` to use the Sortformer diarization""")

class SortformerDiarization:
    def __init__(self, model_name="nvidia/diar_streaming_sortformer_4spk-v2"):
        self.diar_model = SortformerEncLabelModel.from_pretrained(model_name)
        self.diar_model.eval()

        if torch.cuda.is_available():
            self.diar_model.to(torch.device("cuda"))

        # Streaming parameters for speed
        self.diar_model.sortformer_modules.chunk_len = 12
        self.diar_model.sortformer_modules.chunk_right_context = 1
        self.diar_model.sortformer_modules.spkcache_len = 188
        self.diar_model.sortformer_modules.fifo_len = 188
        self.diar_model.sortformer_modules.spkcache_update_period = 144
        self.diar_model.sortformer_modules.log = False
        self.diar_model.sortformer_modules._check_streaming_parameters()

        self.batch_size = 1
        self.processed_signal_offset = torch.zeros((self.batch_size,), dtype=torch.long, device=self.diar_model.device)
        
        self.audio_buffer = np.array([], dtype=np.float32)
        self.sample_rate = 16000
        self.speaker_segments = []

        self.streaming_state = self.diar_model.sortformer_modules.init_streaming_state(
            batch_size=self.batch_size,
            async_streaming=True,
            device=self.diar_model.device
        )
        self.total_preds = torch.zeros((self.batch_size, 0, self.diar_model.sortformer_modules.n_spk), device=self.diar_model.device)


    def _prepare_audio_signal(self, signal):
        audio_signal = torch.tensor(signal).unsqueeze(0).to(self.diar_model.device)
        audio_signal_length = torch.tensor([audio_signal.shape[1]]).to(self.diar_model.device)
        processed_signal, processed_signal_length = self.diar_model.preprocessor(input_signal=audio_signal, length=audio_signal_length)
        return processed_signal, processed_signal_length

    def _create_streaming_loader(self, processed_signal, processed_signal_length):
        streaming_loader = self.diar_model.sortformer_modules.streaming_feat_loader(
            feat_seq=processed_signal,
            feat_seq_length=processed_signal_length,
            feat_seq_offset=self.processed_signal_offset,
        )
        return streaming_loader

    async def diarize(self, pcm_array: np.ndarray):
        """
        Process an incoming audio chunk for diarization.
        """
        self.audio_buffer = np.concatenate([self.audio_buffer, pcm_array])
        
        # Process in fixed-size chunks (e.g., 1 second)
        chunk_size = self.sample_rate # 1 second of audio
        
        while len(self.audio_buffer) >= chunk_size:
            chunk_to_process = self.audio_buffer[:chunk_size]
            self.audio_buffer = self.audio_buffer[chunk_size:]

            processed_signal, processed_signal_length = self._prepare_audio_signal(chunk_to_process)
            
            current_offset_seconds = self.processed_signal_offset.item() * self.diar_model.preprocessor._cfg.window_stride

            streaming_loader = self._create_streaming_loader(processed_signal, processed_signal_length)
            
            frame_duration_s = self.diar_model.sortformer_modules.subsampling_factor * self.diar_model.preprocessor._cfg.window_stride
            chunk_duration_seconds = self.diar_model.sortformer_modules.chunk_len * frame_duration_s

            for i, chunk_feat_seq_t, feat_lengths, left_offset, right_offset in streaming_loader:
                with torch.inference_mode():
                    self.streaming_state, self.total_preds = self.diar_model.forward_streaming_step(
                        processed_signal=chunk_feat_seq_t,
                        processed_signal_length=feat_lengths,
                        streaming_state=self.streaming_state,
                        total_preds=self.total_preds,
                        left_offset=left_offset,
                        right_offset=right_offset,
                    )
                    
                    num_new_frames = feat_lengths[0].item()
                    
                    # Get predictions for the current chunk from the end of total_preds
                    preds_np = self.total_preds[0, -num_new_frames:].cpu().numpy()
                    active_speakers = np.argmax(preds_np, axis=1)

                    for idx, spk in enumerate(active_speakers):
                        start_time = current_offset_seconds + (i * chunk_duration_seconds) + (idx * frame_duration_s)
                        end_time = start_time + frame_duration_s
                        
                        if self.speaker_segments and self.speaker_segments[-1].speaker == spk + 1:
                            self.speaker_segments[-1].end = end_time
                        else:
                            self.speaker_segments.append(SpeakerSegment(
                                speaker=int(spk + 1),
                                start=start_time,
                                end=end_time
                            ))
            
            self.processed_signal_offset += processed_signal_length


    def assign_speakers_to_tokens(self, tokens: list, **kwargs) -> list:
        """
        Assign speakers to tokens based on timing overlap with speaker segments.
        """
        for token in tokens:
            for segment in self.speaker_segments:
                if not (segment.end <= token.start or segment.start >= token.end):
                    token.speaker = segment.speaker
        return tokens

    def close(self):
        """
        Cleanup resources.
        """
        logger.info("Closing SortformerDiarization.")

if __name__ == '__main__':
    import librosa
    an4_audio = 'new_audio_test.mp3'
    signal, sr = librosa.load(an4_audio, sr=16000)

    diarization_pipeline = SortformerDiarization()

    # Simulate streaming
    chunk_size = 16000  # 1 second
    for i in range(0, len(signal), chunk_size):
        chunk = signal[i:i+chunk_size]
        import asyncio
        asyncio.run(diarization_pipeline.diarize(chunk))

    for segment in diarization_pipeline.speaker_segments:
        print(f"Speaker {segment.speaker}: {segment.start:.2f}s - {segment.end:.2f}s")