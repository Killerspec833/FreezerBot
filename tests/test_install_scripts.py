from pathlib import Path


def test_install_copies_requirements_to_usb_root():
    script = Path("/home/nc-small-2/freezerbot/scripts/install.sh").read_text(
        encoding="utf-8"
    )
    assert 'cp "$CLONE_DIR/requirements.txt" "$USB_ROOT/requirements.txt"' in script
