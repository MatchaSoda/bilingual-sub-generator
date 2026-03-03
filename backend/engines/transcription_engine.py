import os
import json
from faster_whisper import WhisperModel

class AudioTranscriptionEngine:
    def __init__(self, model_size="base", computing_device="cpu", calculation_precision="int8"):
        print(f"📡 Loading Whisper model: {model_size} ({computing_device}/{calculation_precision})...", flush=True)
        self.whisper_model = WhisperModel(model_size, device=computing_device, compute_type=calculation_precision)
        print("✅ Model loaded.", flush=True)

    def transcribe_audio_file(self, audio_file_path, specified_language=None, cached_results_path=None):
        if cached_results_path and os.path.exists(cached_results_path):
            return self._load_results_from_cache(cached_results_path)

        print(f"👂 Transcribing: {audio_file_path}", flush=True)
        
        raw_segments_generator, transcription_info = self.whisper_model.transcribe(
            audio_file_path, 
            beam_size=5, 
            language=specified_language,
            word_timestamps=True 
        )
        
        print(f"✅ Detected language: {transcription_info.language} (prob: {transcription_info.language_probability:.2f})", flush=True)
        
        processed_segments = []
        for segment in raw_segments_generator:
            print(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}", flush=True)
            
            segment_data = {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
                "words": self._extract_word_timestamps(segment)
            }
            processed_segments.append(segment_data)
        
        transcription_output = {
            "language": transcription_info.language,
            "segments": processed_segments
        }

        if cached_results_path:
            self._save_results_to_cache(transcription_output, cached_results_path)

        return transcription_output

    def _extract_word_timestamps(self, segment):
        if not segment.words:
            return []
            
        word_data_list = []
        for word_info in segment.words:
            word_data_list.append({
                "start": word_info.start, 
                "end": word_info.end, 
                "word": word_info.word.strip()
            })
        return word_data_list

    def _load_results_from_cache(self, cache_path):
        print(f"📦 Loading cached ASR results from: {cache_path}", flush=True)
        try:
            with open(cache_path, 'r', encoding='utf-8') as cache_file:
                return json.load(cache_file)
        except Exception as error:
            print(f"⚠️ Cache read failed: {error}, falling back to transcription", flush=True)
            return None

    def _save_results_to_cache(self, data, cache_path):
        print(f"💾 Saving ASR results to cache: {cache_path}", flush=True)
        with open(cache_path, 'w', encoding='utf-8') as cache_file:
            json.dump(data, cache_file, ensure_ascii=False, indent=2)
