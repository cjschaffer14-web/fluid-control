"""Build a local macOS app using the active Python environment; no downloads."""
from pathlib import Path
import argparse
import json
import plistlib
import shutil
import subprocess
import sys
import sysconfig
import tempfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'src'))
from version import VERSION, BUILD


def python_library():
    candidates = [Path(sys.base_prefix)/'Python']
    libdir, library = sysconfig.get_config_var('LIBDIR'), sysconfig.get_config_var('LDLIBRARY')
    if libdir and library:
        candidates.append(Path(libdir)/library)
    for candidate in candidates:
        if candidate.is_file() and candidate.suffix != '.a':
            return candidate.resolve()
    raise SystemExit('Python needs a loadable shared library or framework. Rebuild using a compatible interpreter.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=ROOT/'models/hand_landmarker.task')
    parser.add_argument('--speech-model', type=Path, help='Optional extracted Vosk model directory')
    parser.add_argument('--output', type=Path, default=ROOT/'dist/Control.app')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Building requires macOS.')
    if not args.model.is_file():
        parser.error('Hand model missing; download it as described in README.md or use --model.')
    if args.speech_model and not args.speech_model.is_dir():
        parser.error('--speech-model must be an extracted Vosk model directory.')
    output = args.output.expanduser().absolute()
    if output.exists():
        parser.error(f'Output already exists: {output}. Choose a fresh --output path or remove that build yourself.')
    if output.suffix != '.app':
        parser.error('--output must end in .app')
    library = python_library()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fluid-control-build-') as temp:
        temp = Path(temp)
        app = temp/'Control.app'
        contents = app/'Contents'
        resources = contents/'Resources'
        resources.mkdir(parents=True)
        (contents/'MacOS').mkdir()
        config = dict(CONTROL_PYHOME=sys.base_prefix,
                      CONTROL_SITE=sysconfig.get_path('purelib'), CONTROL_PYLIB=str(library))
        (temp/'runtime_config.h').write_text('\n'.join(
            f'#define {key} {json.dumps(value)}' for key, value in config.items())+'\n')
        subprocess.run(['clang', '-O2', '-fobjc-arc', '-Wl,-export_dynamic', '-I', str(temp),
                        '-framework', 'Cocoa', '-framework', 'AVFoundation',
                        '-framework', 'ApplicationServices', '-framework', 'Carbon',
                        str(ROOT/'launcher.m'), '-o', str(contents/'MacOS/Control')], check=True)
        for source in (ROOT/'src').glob('*.py'):
            shutil.copyfile(source, resources/source.name)
        shutil.copyfile(args.model, resources/'hand_landmarker.task')
        if args.speech_model:
            shutil.copytree(args.speech_model, resources/'vosk-model-small-en-us-0.15', copy_function=shutil.copyfile)
        iconset = temp/'Control.iconset'
        iconset.mkdir()
        # The source icon is 256 px. Preserve that resolution rather than inventing larger artwork.
        for size in (16, 32, 128, 256):
            subprocess.run(['sips', '-z', str(size), str(size), str(ROOT/'assets/icon.png'),
                            '--out', str(iconset/f'icon_{size}x{size}.png')], check=True, stdout=subprocess.DEVNULL)
        for size in (16, 128):
            shutil.copyfile(iconset/f'icon_{size*2}x{size*2}.png', iconset/f'icon_{size}x{size}@2x.png')
        subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(resources/'Control-v02.icns')], check=True)
        for name in ('README.md', 'VALIDATION.md', 'THIRD_PARTY.md'):
            shutil.copyfile(ROOT/name, resources/name)
        info = dict(CFBundleIdentifier='local.control.desktop', CFBundleName='Control',
                    CFBundleDisplayName='Control', CFBundleExecutable='Control', CFBundlePackageType='APPL',
                    CFBundleVersion=BUILD, CFBundleShortVersionString=VERSION, LSMinimumSystemVersion='14.0',
                    LSUIElement=False, NSHighResolutionCapable=True, CFBundleIconFile='Control-v02.icns',
                    NSCameraUsageDescription='Control uses your camera to recognize intentional hand movements. Video stays on your Mac.',
                    NSMicrophoneUsageDescription='Control listens locally for one command when you activate Voice.',
                    NSAppleEventsUsageDescription='Control adjusts system volume when you ask.')
        (contents/'Info.plist').write_bytes(plistlib.dumps(info))
        subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
        subprocess.run(['ditto', '--norsrc', '--noextattr', str(app), str(output)], check=True)
    subprocess.run(['codesign', '--verify', str(output)], check=True)
    print(f'Built {output}\nKeep the Python interpreter and environment in place; this is a local build.')


if __name__ == '__main__':
    main()
