"""SUDO_ASKPASS helper: asks for the user's password in a GTK dialog.

sudo runs this program when it has no terminal, passes its prompt as argv[1]
and reads the password from stdout. Exit status 1 means "cancelled".
The password is written to stdout only; it is never logged or stored.
"""
from __future__ import annotations

import sys


def run(argv: list[str]) -> int:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    prompt = argv[1] if len(argv) > 1 else "Password:"

    dialog = Gtk.Dialog(title="Pangolin", modal=True)
    dialog.set_icon_name("network-vpn")
    dialog.set_keep_above(True)
    dialog.set_position(Gtk.WindowPosition.CENTER)
    dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Authenticate", Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)

    box = dialog.get_content_area()
    box.set_border_width(12)
    box.set_spacing(8)
    title = Gtk.Label(xalign=0)
    title.set_markup("<b>Administrator rights required</b>")
    box.add(title)
    info = Gtk.Label(
        label="Pangolin needs administrator rights to create the network tunnel.",
        xalign=0, wrap=True, max_width_chars=48)
    box.add(info)
    hint = Gtk.Label(label=prompt.strip(), xalign=0)
    hint.get_style_context().add_class("dim-label")
    box.add(hint)
    entry = Gtk.Entry(visibility=False, activates_default=True,
                      input_purpose=Gtk.InputPurpose.PASSWORD)
    box.add(entry)

    dialog.show_all()
    entry.grab_focus()
    response = dialog.run()
    password = entry.get_text()
    entry.set_text("")
    dialog.destroy()

    if response != Gtk.ResponseType.OK:
        return 1
    sys.stdout.write(password + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv))
