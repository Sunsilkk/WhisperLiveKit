import numpy as np
import torch
import logging
from whisperlivekit.timed_objects import SpeakerSegment
from typing import Optional, Any

logger = logging.getLogger(__name__)

try:
    from nemo.collections.asr.models import SortformerEncLabelModel
except ImportError:
    raise SystemExit("""Please use `pip install "git+https://github.com/NVIDIA/NeMo.git@main#egg=nemo_toolkit[asr]"` to use the Sortformer diarization""")

class SortformerDiarization:
    def __init__(self, model_name="nvidia/diar_streaming_sortformer_4spk-v2"):
        self.diar_model: Optional[Any] = None
        try:
            self.diar_model = SortformerEncLabelModel.from_pretrained(model_name)
        except Exception as e:
            logger.error(f"Failed to load SortformerEncLabelModel: {e}")
            self.diar_model = None
            return
        if self.diar_model is not None:
            self.diar_model.eval()

            if torch.cuda.is_available():
                self.diar_model.to(torch.device("cuda"))

            # Streaming parameters for speed
            if hasattr(self.diar_model, 'sortformer_modules'):
                self.diar_model.sortformer_modules.chunk_len = 12
                self.diar_model.sortformer_modules.chunk_right_context = 1
                self.diar_model.sortformer_modules.spkcache_len = 188
                self.diar_model.sortformer_modules.fifo_len = 188
                self.diar_model.sortformer_modules.spkcache_update_period = 144
                self.diar_model.sortformer_modules.log = False
                if hasattr(self.diar_model.sortformer_modules, '_check_streaming_parameters'):
                    self.diar_model.sortformer_modules._check_streaming_parameters()

        self.batch_size = 1
        device = getattr(self.diar_model, 'device', torch.device("cpu")) if self.diar_model is not None else torch.device("cpu")
        self.processed_signal_offset = torch.zeros((self.batch_size,), dtype=torch.long, device=device)

        self.audio_buffer = np.array([], dtype=np.float32)
        self.sample_rate = 16000
        self.speaker_segments = []

        if self.diar_model is not None and hasattr(self.diar_model, 'sortformer_modules'):
            sortformer_modules = getattr(self.diar_model, 'sortformer_modules')
            self.streaming_state = sortformer_modules.init_streaming_state(
                batch_size=self.batch_size,
                async_streaming=True,
                device=device
            )
            n_spk = getattr(sortformer_modules, 'n_spk', 4)
            self.total_preds = torch.zeros((self.batch_size, 0, n_spk), device=device)
        else:
            self.streaming_state = None
            self.total_preds = None


    def _prepare_audio_signal(self, signal):
        if self.diar_model is None:
            return None, None
        device = getattr(self.diar_model, 'device', torch.device("cpu"))
        audio_signal = torch.tensor(signal).unsqueeze(0).to(device)
        audio_signal_length = torch.tensor([audio_signal.shape[1]]).to(device)
        preprocessor = getattr(self.diar_model, 'preprocessor', None)
        if preprocessor is not None:
            processed_signal, processed_signal_length = preprocessor(input_signal=audio_signal, length=audio_signal_length)
            return processed_signal, processed_signal_length
        return None, None

    def _create_streaming_loader(self, processed_signal, processed_signal_length):
        if self.diar_model is None or not hasattr(self.diar_model, 'sortformer_modules'):
            return None
        sortformer_modules = getattr(self.diar_model, 'sortformer_modules')
        streaming_loader = sortformer_modules.streaming_feat_loader(
            feat_seq=processed_signal,
            feat_seq_length=processed_signal_length,
            feat_seq_offset=self.processed_signal_offset,
        )
        return streaming_loader

    async def diarize(self, pcm_array: np.ndarray):
        """
        Process an incoming audio chunk for diarization.
        """
        if self.diar_model is None:
            logger.warning("Diarization model not loaded, skipping processing")
            return

        self.audio_buffer = np.concatenate([self.audio_buffer, pcm_array])

        # Process in fixed-size chunks (e.g., 1 second)
        chunk_size = self.sample_rate # 1 second of audio

        while len(self.audio_buffer) >= chunk_size:
            chunk_to_process = self.audio_buffer[:chunk_size]
            self.audio_buffer = self.audio_buffer[chunk_size:]

            processed_signal, processed_signal_length = self._prepare_audio_signal(chunk_to_process)
            if processed_signal is None:
                continue

            preprocessor = getattr(self.diar_model, 'preprocessor', None)
            window_stride = getattr(getattr(preprocessor, '_cfg', None), 'window_stride', 0.02) if preprocessor else 0.02
            current_offset_seconds = self.processed_signal_offset.item() * window_stride

            streaming_loader = self._create_streaming_loader(processed_signal, processed_signal_length)
            if streaming_loader is None:
                continue

            sortformer_modules = getattr(self.diar_model, 'sortformer_modules', None)
            subsampling_factor = getattr(sortformer_modules, 'subsampling_factor', 1) if sortformer_modules else 1
            chunk_len = getattr(sortformer_modules, 'chunk_len', 12) if sortformer_modules else 12
            frame_duration_s = subsampling_factor * window_stride
            chunk_duration_seconds = chunk_len * frame_duration_s

            for i, chunk_feat_seq_t, feat_lengths, left_offset, right_offset in streaming_loader:
                with torch.inference_mode():
                    forward_streaming_step = getattr(self.diar_model, 'forward_streaming_step', None)
                    if forward_streaming_step is not None:
                        self.streaming_state, self.total_preds = forward_streaming_step(
                            processed_signal=chunk_feat_seq_t,
                            processed_signal_length=feat_lengths,
                            streaming_state=self.streaming_state,
                            total_preds=self.total_preds,
                            left_offset=left_offset,
                            right_offset=right_offset,
                        )

                        if self.total_preds is not None:
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

            if processed_signal_length is not None:
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

    def insert_silence(self, silence_duration):
        """Handle silence in audio stream."""
        logger.debug(f"Inserting silence: {silence_duration} seconds")
        # Update timing offset for silence
        pass

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
