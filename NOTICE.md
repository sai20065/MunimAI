# Third-party notices

SaralcreditAI's own code is under the MIT licence (see `LICENSE`). It uses the following free, openly licensed components.
Check each project's own licence file for the authoritative text.

| Component | Used for | Licence |
|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Local English speech-to-text (separate virtual environment on D:) | MIT |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | Inference engine under faster-whisper | MIT |
| OpenAI Whisper model weights (`small.en`, converted by Systran) | Speech recognition model | MIT (as labelled on the model card; confirm there) |
| [PyAV](https://github.com/PyAV-Org/PyAV) | Installed as a dependency of faster-whisper (we decode audio ourselves with ffmpeg) | BSD-3-Clause |
| [lucide](https://lucide.dev) icons | Interface icons | ISC |
| Qwen2.5-7B-Instruct | Main language model | Apache 2.0 |
| Gemma 3 4B and Gemma 3n E4B | Helper and second-opinion models | Google Gemma Terms of Use (free to use; read the terms) |
| OpenStax Principles of Finance 2e, Principles of Marketing, Entrepreneurship | Retrieval-only reading notes with attribution (never used for training) | CC BY-NC-SA 4.0: non-commercial and share-alike. Set `LIBRARY_ALLOW_NC=0` to hide them before any commercial use. |
| [axe-core](https://github.com/dequelabs/axe-core) | Accessibility checks while developing (not shipped) | MPL-2.0 |
| Bhashini | Hindi and Kannada speech, translation and voice | Government of India service; follow its terms of use |

Desktop dictation apps such as Handy, OpenWhispr and Whispering (MIT) are separate programs and are not part of this project.
