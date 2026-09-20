import subprocess
import pytest


def _has(tool):
    return subprocess.run(["which", tool], capture_output=True).returncode == 0


requires_ffmpeg = pytest.mark.skipif(not _has("ffmpeg"), reason="ffmpeg not installed")


@pytest.fixture
def make_video(tmp_path):
    """Create a tiny real MP4. rotate=None leaves no display matrix."""
    def _make(name="v.mp4", w=320, h=240, seconds=1, rotate=None):
        out = tmp_path / name
        cmd = ["ffmpeg", "-v", "error", "-y",
               "-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate=30:duration={seconds}",
               "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
               "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-shortest"]
        if rotate is not None:
            cmd += ["-metadata:s:v:0", f"rotate={rotate}"]
        cmd.append(str(out))
        subprocess.run(cmd, check=True, capture_output=True)
        return out
    return _make
