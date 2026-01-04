"""
Music separation and processing utilities
For Python 3.14 compatibility, we're using a simplified approach
"""

import os
import tempfile
import shutil
import numpy as np
import librosa
import soundfile as sf
from pathlib import Path
import cloudinary
import cloudinary.uploader
import json
from datetime import datetime


class MusicProcessor:
    """Handle music upload and Cloudinary uploads"""
    
    def __init__(self):
        """Initialize Cloudinary configuration"""
        self.cloudinary_configured = False
        if (os.getenv('CLOUDINARY_CLOUD_NAME') and 
            os.getenv('CLOUDINARY_API_KEY') and 
            os.getenv('CLOUDINARY_API_SECRET')):
            cloudinary.config(
                cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
                api_key=os.getenv('CLOUDINARY_API_KEY'),
                api_secret=os.getenv('CLOUDINARY_API_SECRET')
            )
            self.cloudinary_configured = True
    
    def separate_audio_simple(self, audio_path):
        """
        Extract different instruments from audio using advanced frequency and temporal separation
        Identifies: vocals, drums, bass, guitar, piano, flute, strings, and background sounds
        Works with any audio length (min 0.5 seconds)
        
        Args:
            audio_path: Path to input audio file
        
        Returns:
            tuple: (dict with stem paths, temp_dir path)
        """
        try:
            print(f"🎵 Loading audio: {audio_path}")
            
            # Load audio file
            y, sr = librosa.load(audio_path, sr=22050)  # Standardize to 22050Hz
            duration = librosa.get_duration(y=y, sr=sr)
            print(f"✓ Audio loaded: {duration:.2f}s at {sr}Hz, shape: {y.shape}")
            
            # Ensure audio is not too short
            if duration < 0.5:
                raise Exception(f"Audio too short ({duration:.2f}s). Minimum 0.5 seconds required")
            
            # Create temporary directory
            temp_dir = tempfile.mkdtemp()
            output_files = {}
            
            print("🔄 Separating audio using HPSS...")
            # HPSS: Harmonic/Percussive Source Separation
            y_harmonic, y_percussive = librosa.effects.hpss(y, margin=2.0)
            print(f"✓ HPSS complete - Harmonic: {y_harmonic.shape}, Percussive: {y_percussive.shape}")
            
            # Get frequency bins for analysis
            S_harmonic = librosa.magphase(librosa.stft(y_harmonic))[0]
            S_percussive = librosa.magphase(librosa.stft(y_percussive))[0]
            freqs = librosa.fft_frequencies(sr=sr)
            S_harmonic_phase = np.angle(librosa.stft(y_harmonic))
            S_percussive_phase = np.angle(librosa.stft(y_percussive))
            
            # ============ VOCALS ============
            print("🎤 Extracting vocals...")
            vocal_mask = np.zeros_like(freqs)
            # Vocals typically 80Hz - 4000Hz with emphasis on 150Hz-3000Hz
            vocal_idx = (freqs > 80) & (freqs < 4000)
            vocal_mask[vocal_idx] = 1.2
            mid_idx = (freqs > 150) & (freqs < 3000)
            vocal_mask[mid_idx] *= 1.3
            
            S_vocal = S_harmonic * vocal_mask[:, np.newaxis]
            D_vocal = S_vocal * np.exp(1j * S_harmonic_phase)
            y_vocals = librosa.istft(D_vocal)
            y_vocals = self._normalize_audio(y_vocals)
            vocals_path = os.path.join(temp_dir, 'vocals.wav')
            sf.write(vocals_path, y_vocals, sr)
            output_files['vocals'] = vocals_path
            print(f"✓ Vocals saved: {vocals_path}")
            
            # ============ DRUMS ============
            print("🥁 Extracting drums...")
            # Drums are primarily percussive with emphasis on lower frequencies
            drums_mask = np.ones_like(freqs)
            # Reduce very low and very high frequencies to focus on drum range (50Hz-5kHz)
            low_reduce = freqs < 50
            high_reduce = freqs > 5000
            drums_mask[low_reduce] = 0.3
            drums_mask[high_reduce] = 0.3
            
            S_drums = S_percussive * drums_mask[:, np.newaxis]
            D_drums = S_drums * np.exp(1j * S_percussive_phase)
            y_drums = librosa.istft(D_drums)
            y_drums = self._normalize_audio(y_drums)
            drums_path = os.path.join(temp_dir, 'drums.wav')
            sf.write(drums_path, y_drums, sr)
            output_files['drums'] = drums_path
            print(f"✓ Drums saved: {drums_path}")
            
            # ============ BASS ============
            print("🔊 Extracting bass...")
            # Bass: low frequencies from harmonic (20Hz - 200Hz)
            bass_mask = np.zeros_like(freqs)
            bass_idx = (freqs > 20) & (freqs < 250)
            bass_mask[bass_idx] = 1.8
            sub_bass_idx = (freqs > 20) & (freqs < 100)
            bass_mask[sub_bass_idx] *= 1.2
            
            S_bass = S_harmonic * bass_mask[:, np.newaxis]
            D_bass = S_bass * np.exp(1j * S_harmonic_phase)
            y_bass = librosa.istft(D_bass)
            y_bass = self._normalize_audio(y_bass)
            bass_path = os.path.join(temp_dir, 'bass.wav')
            sf.write(bass_path, y_bass, sr)
            output_files['bass'] = bass_path
            print(f"✓ Bass saved: {bass_path}")
            
            # ============ GUITAR ============
            print("🎸 Extracting guitar...")
            # Guitar: mid-range frequencies (80Hz - 2kHz)
            guitar_mask = np.zeros_like(freqs)
            guitar_idx = (freqs > 80) & (freqs < 2000)
            guitar_mask[guitar_idx] = 1.4
            # Emphasize fundamental frequencies of guitar
            guitar_strong_idx = (freqs > 200) & (freqs < 1000)
            guitar_mask[guitar_strong_idx] *= 1.2
            
            S_guitar = S_harmonic * guitar_mask[:, np.newaxis]
            D_guitar = S_guitar * np.exp(1j * S_harmonic_phase)
            y_guitar = librosa.istft(D_guitar)
            y_guitar = self._normalize_audio(y_guitar)
            guitar_path = os.path.join(temp_dir, 'guitar.wav')
            sf.write(guitar_path, y_guitar, sr)
            output_files['guitar'] = guitar_path
            print(f"✓ Guitar saved: {guitar_path}")
            
            # ============ PIANO ============
            print("🎹 Extracting piano...")
            # Piano: wide frequency range with emphasis 27Hz - 4186Hz, but distributed
            piano_mask = np.zeros_like(freqs)
            piano_idx = (freqs > 27) & (freqs < 4200)
            piano_mask[piano_idx] = 0.8
            # Piano has distinct harmonic series
            piano_mid = (freqs > 200) & (freqs < 2000)
            piano_mask[piano_mid] *= 1.3
            
            S_piano = S_harmonic * piano_mask[:, np.newaxis]
            D_piano = S_piano * np.exp(1j * S_harmonic_phase)
            y_piano = librosa.istft(D_piano)
            y_piano = self._normalize_audio(y_piano)
            piano_path = os.path.join(temp_dir, 'piano.wav')
            sf.write(piano_path, y_piano, sr)
            output_files['piano'] = piano_path
            print(f"✓ Piano saved: {piano_path}")
            
            # ============ FLUTE & WOODWINDS ============
            print("🪶 Extracting flute & woodwinds...")
            # Flute: high frequencies 261Hz - 4186Hz with bright character
            flute_mask = np.zeros_like(freqs)
            flute_idx = (freqs > 250) & (freqs < 4200)
            flute_mask[flute_idx] = 0.9
            flute_bright = (freqs > 1000) & (freqs < 3500)
            flute_mask[flute_bright] *= 1.4
            
            S_flute = S_harmonic * flute_mask[:, np.newaxis]
            D_flute = S_flute * np.exp(1j * S_harmonic_phase)
            y_flute = librosa.istft(D_flute)
            y_flute = self._normalize_audio(y_flute)
            flute_path = os.path.join(temp_dir, 'flute.wav')
            sf.write(flute_path, y_flute, sr)
            output_files['flute'] = flute_path
            print(f"✓ Flute saved: {flute_path}")
            
            # ============ STRINGS ============
            print("🎻 Extracting strings...")
            # Strings: mid-high frequencies 40Hz - 3500Hz with natural decay
            strings_mask = np.zeros_like(freqs)
            strings_idx = (freqs > 40) & (freqs < 3500)
            strings_mask[strings_idx] = 0.9
            strings_body = (freqs > 150) & (freqs < 1500)
            strings_mask[strings_body] *= 1.3
            
            S_strings = S_harmonic * strings_mask[:, np.newaxis]
            D_strings = S_strings * np.exp(1j * S_harmonic_phase)
            y_strings = librosa.istft(D_strings)
            y_strings = self._normalize_audio(y_strings)
            strings_path = os.path.join(temp_dir, 'strings.wav')
            sf.write(strings_path, y_strings, sr)
            output_files['strings'] = strings_path
            print(f"✓ Strings saved: {strings_path}")
            
            # ============ HIGH FREQUENCY ELEMENTS (background, ambience) ============
            print("✨ Extracting background & ambience...")
            # Background/Ambience: high frequencies and reverb
            bg_mask = np.zeros_like(freqs)
            bg_idx = (freqs > 3000)
            bg_mask[bg_idx] = 1.2
            very_high = freqs > 5000
            bg_mask[very_high] *= 1.1
            
            S_background = S_harmonic * bg_mask[:, np.newaxis]
            D_background = S_background * np.exp(1j * S_harmonic_phase)
            y_background = librosa.istft(D_background)
            y_background = self._normalize_audio(y_background)
            background_path = os.path.join(temp_dir, 'background.wav')
            sf.write(background_path, y_background, sr)
            output_files['background'] = background_path
            print(f"✓ Background saved: {background_path}")
            
            # ============ INSTRUMENTAL (remaining percussive that's not drums) ============
            print("🎺 Extracting other instruments...")
            # Brass, percussion effects, etc. - remaining percussive content
            instr_mask = np.ones_like(freqs)
            instr_mask[freqs < 100] *= 0.5  # Reduce sub-bass
            
            S_instrumental = S_percussive * instr_mask[:, np.newaxis]
            D_instrumental = S_instrumental * np.exp(1j * S_percussive_phase)
            y_instrumental = librosa.istft(D_instrumental)
            y_instrumental = self._normalize_audio(y_instrumental)
            instrumental_path = os.path.join(temp_dir, 'instrumental.wav')
            sf.write(instrumental_path, y_instrumental, sr)
            output_files['instrumental'] = instrumental_path
            print(f"✓ Instrumental saved: {instrumental_path}")
            
            print(f"\n✅ Processing complete!")
            print(f"   Stems created: {list(output_files.keys())}")
            print(f"   Total files: {len(output_files)}")
            
            return output_files, temp_dir
        
        except Exception as e:
            print(f"❌ Error during audio processing: {str(e)}")
            raise Exception(f"Audio processing failed: {str(e)}")
    
    def _normalize_audio(self, audio, target_level=0.95):
        """
        Normalize audio to prevent clipping while maintaining dynamics
        
        Args:
            audio: Audio signal
            target_level: Target peak level (0-1)
        
        Returns:
            Normalized audio
        """
        max_val = np.max(np.abs(audio))
        if max_val > 0:
            return audio * (target_level / max_val)
        return audio
    
    def upload_to_cloudinary(self, file_path, public_id, folder='music_separation'):
        """
        Upload audio file to Cloudinary with proper error handling
        
        Args:
            file_path: Path to audio file
            public_id: Public ID for the file in Cloudinary
            folder: Folder name in Cloudinary
        
        Returns:
            dict: Upload response with URL and other metadata
        """
        if not self.cloudinary_configured:
            # Check individual env vars for better debugging
            cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME')
            api_key = os.getenv('CLOUDINARY_API_KEY')
            api_secret = os.getenv('CLOUDINARY_API_SECRET')
            
            missing = []
            if not cloud_name:
                missing.append('CLOUDINARY_CLOUD_NAME')
            if not api_key:
                missing.append('CLOUDINARY_API_KEY')
            if not api_secret:
                missing.append('CLOUDINARY_API_SECRET')
            
            raise Exception(f"Cloudinary is not configured. Missing environment variables: {', '.join(missing)}. Please set these in your .env file.")
        
        try:
            print(f"Uploading to Cloudinary: {public_id}")
            
            # Verify file exists before uploading
            if not os.path.exists(file_path):
                raise Exception(f"File does not exist: {file_path}")
            
            # Get file size for logging
            file_size = os.path.getsize(file_path) / (1024 * 1024)
            print(f"File size: {file_size:.2f}MB")
            
            # Upload with proper parameters
            response = cloudinary.uploader.upload(
                file_path,
                resource_type='video',  # Audio files use 'video' resource type in Cloudinary
                public_id=f"{folder}/{public_id}",
                overwrite=True,  # Allow overwriting if same public_id
                timeout=300  # 5 minutes timeout for large files
            )
            
            if not response.get('secure_url'):
                raise Exception(f"Upload successful but no URL returned. Response: {response}")
            
            print(f"✓ Upload successful: {response.get('secure_url')}")
            return response
        
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Error uploading to Cloudinary: {error_msg}")
            
            # Check for common Cloudinary errors
            if 'authentication' in error_msg.lower():
                raise Exception(f"Cloudinary authentication failed. Check your API credentials.")
            elif 'timeout' in error_msg.lower():
                raise Exception(f"Upload timeout. File may be too large or connection too slow.")
            elif 'invalid' in error_msg.lower():
                raise Exception(f"Invalid Cloudinary configuration: {error_msg}")
            else:
                raise Exception(f"Cloudinary upload failed: {error_msg}")
    
    def process_and_upload(self, audio_file_path, project_id, user_id):
        """
        Complete workflow: process audio and upload all stems to Cloudinary
        
        Args:
            audio_file_path: Path to input audio file
            project_id: Firestore project ID
            user_id: Firebase user ID
        
        Returns:
            dict: Results with all stem URLs and metadata
        """
        import shutil
        
        temp_dir = None
        try:
            # Step 1: Process audio
            stems, temp_dir = self.separate_audio_simple(audio_file_path)
            
            # Step 2: Upload each stem to Cloudinary
            results = {
                'stems': {},
                'timestamp': datetime.now().isoformat(),
                'total_stems': len(stems)
            }
            
            for stem_name, stem_path in stems.items():
                try:
                    # Verify file exists before uploading
                    if not os.path.exists(stem_path):
                        print(f"Warning: File not found: {stem_path}")
                        results['stems'][stem_name] = {
                            'url': None,
                            'error': f'File not found: {stem_path}'
                        }
                        continue
                    
                    # Create unique public ID
                    public_id = f"{user_id}/{project_id}/{stem_name}_{datetime.now().timestamp()}"
                    
                    # Upload to Cloudinary
                    upload_response = self.upload_to_cloudinary(stem_path, public_id)
                    
                    results['stems'][stem_name] = {
                        'url': upload_response.get('secure_url'),
                        'public_id': upload_response.get('public_id'),
                        'format': upload_response.get('format'),
                        'size': upload_response.get('bytes')
                    }
                    print(f"✓ Successfully uploaded {stem_name}")
                    
                except Exception as e:
                    print(f"Error uploading stem {stem_name}: {str(e)}")
                    results['stems'][stem_name] = {
                        'url': None,
                        'error': str(e)
                    }
            
            return results
        
        except Exception as e:
            print(f"Error in process_and_upload: {str(e)}")
            raise Exception(f"Processing failed: {str(e)}")
        
        finally:
            # Clean up temporary directory
            if temp_dir and os.path.exists(temp_dir):
                print(f"Cleaning up temp directory: {temp_dir}")
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def get_audio_duration(self, audio_path):
        """
        Get duration of audio file in seconds
        
        Args:
            audio_path: Path to audio file
        
        Returns:
            float: Duration in seconds
        """
        try:
            y, sr = librosa.load(audio_path, sr=None)
            duration = librosa.get_duration(y=y, sr=sr)
            return duration
        except Exception as e:
            print(f"Error getting audio duration: {str(e)}")
            return None


def get_instrument_emoji(stem_name):
    """Get emoji for instrument name"""
    stem_lower = stem_name.lower()
    emojis = {
        'vocals': '🎤',
        'drums': '🥁',
        'bass': '🔊',
        'guitar': '🎸',
        'piano': '🎹',
        'flute': '🪶',
        'strings': '🎻',
        'instrumental': '🎺',
        'background': '✨',
        'ambience': '✨',
        'other': '🎼',
        'accompaniment': '🎶'
    }
    
    for key, emoji in emojis.items():
        if key in stem_lower:
            return emoji
    
    return '🎵'


def format_stem_name(stem_name):
    """Format stem name for display"""
    # Convert underscore to space and capitalize
    return ' '.join(word.capitalize() for word in stem_name.split('_'))

