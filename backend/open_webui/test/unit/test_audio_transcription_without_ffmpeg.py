from types import SimpleNamespace

import pytest

from open_webui.routers import audio


HEADERS = {
    "wav": b"RIFF\x00\x00\x00\x00WAVEfmt ",
    "ogg": b"OggS\x00\x02\x00\x00\x00\x00\x00\x00",
    "webm": b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81",
    "m4a": b"\x00\x00\x00\x1cftypM4A ",
    "mp3": b"ID3\x04\x00\x00\x00\x00\x00\x00\x00\x00",
}


@pytest.mark.parametrize("ext", sorted(HEADERS))
def test_sniff_audio_extension(tmp_path, ext):
    path = tmp_path / "recording.wav"  # the browser's name, whatever it recorded
    path.write_bytes(HEADERS[ext] + b"\x00" * 64)
    assert audio.sniff_audio_extension(str(path)) == ext


def test_sniff_audio_extension_unknown(tmp_path):
    path = tmp_path / "recording.wav"
    path.write_bytes(b"not audio at all")
    assert audio.sniff_audio_extension(str(path)) is None


def test_strip_sensevoice_tags():
    assert audio.strip_sensevoice_tags("今天天气怎么样？😊") == "今天天气怎么样？"
    assert audio.strip_sensevoice_tags("🎼 hello 😡 ") == "hello"
    assert audio.strip_sensevoice_tags("没有标记") == "没有标记"


def test_openai_stt_without_ffmpeg_uploads_the_recording_as_is(tmp_path, monkeypatch):
    path = tmp_path / "abc.wav"
    path.write_bytes(HEADERS["webm"] + b"\x00" * 64)
    sent = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"text": "帮我查一下明天的天气。😊"}

    def fake_post(url, headers, files, data, verify):
        sent["url"] = url
        sent["name"] = files["file"][0]
        sent["data"] = data
        return Response()

    monkeypatch.setattr(audio.shutil, "which", lambda _name: None)
    monkeypatch.setattr(audio.requests, "post", fake_post)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    STT_ENGINE="openai",
                    STT_MODEL="FunAudioLLM/SenseVoiceSmall",
                    STT_OPENAI_API_BASE_URL="https://stt.example/v1",
                    STT_OPENAI_API_KEY="k",
                )
            )
        )
    )

    data = audio.transcribe(request, str(path), language="zh")

    assert sent["url"] == "https://stt.example/v1/audio/transcriptions"
    assert sent["name"] == "abc.webm"
    assert sent["data"] == {"model": "FunAudioLLM/SenseVoiceSmall", "language": "zh"}
    assert data["text"] == "帮我查一下明天的天气。"
