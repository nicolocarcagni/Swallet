# main.py
#
# Copyright 2026 nicolocarcagni
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
import logging
import gi

logging.basicConfig(level=logging.ERROR, format='%(levelname)s: %(message)s')

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gio, Adw
from .window import SwalletWindow


class SwalletApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self):
        super().__init__(application_id='io.github.nicolocarcagni.Swallet',
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
                         resource_base_path='/io/github/nicolocarcagni/Swallet')
        self.create_action('quit', lambda *_: self.quit(), ['<control>q'])
        self.create_action('about', self.on_about_action)
        self.create_action('preferences', self.on_preferences_action)

    def do_activate(self):
        """Called when the application is activated.

        We raise the application's main window, creating it if
        necessary.
        """
        win = self.props.active_window
        if not win:
            win = SwalletWindow(application=self)
        win.present()

    def on_about_action(self, *args):
        """Callback for the app.about action."""
        # Singleton pattern / Lazy instantiation
        if hasattr(self, '_about_dialog') and self._about_dialog:
            self._about_dialog.present(self.props.active_window)
            return

        self._about_dialog = Adw.AboutDialog(
            application_name='Swallet',
            application_icon='io.github.nicolocarcagni.Swallet',
            developer_name='Nicolò Carcagni',
            version='2.0.0',
            developers=['Nicolò Carcagni https://github.com/nicolocarcagni'],
            copyright='© 2026 Nicolò Carcagni',
            license_type=Gtk.License.GPL_3_0,
            website='https://github.com/nicolocarcagni/Swallet',
            issue_url='https://github.com/nicolocarcagni/Swallet/issues',
        )

        # Lazy load the COPYING file using non-blocking/on-demand I/O
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        copying_path = os.path.join(base_dir, 'COPYING')
        
        try:
            # Fallback path for Flatpak execution scopes
            if not os.path.exists(copying_path):
                copying_path = '/app/share/licenses/swallet/COPYING'
                
            if os.path.exists(copying_path):
                with open(copying_path, 'r', encoding='utf-8') as f:
                    self._about_dialog.set_license(f.read())
        except Exception as e:
            logging.warning(f"Could not read COPYING file: {e}")

        # Ensure memory is properly freed upon dismissal
        def on_closed(dialog):
            self._about_dialog = None
            
        self._about_dialog.connect('closed', on_closed)
        self._about_dialog.present(self.props.active_window)

    def on_preferences_action(self, widget, _):
        """Callback for the app.preferences action."""
        win = self.props.active_window
        if win and hasattr(win, 'api'):
            from .preferences import PreferencesWindow
            pref_win = PreferencesWindow(
                api_client=win.api,
                wallet_path=win.wallet_path,
            )
            pref_win.set_transient_for(win)
            pref_win.present()
        else:
            logging.error("Cannot open preferences: active window has no api client initialized.")

    def create_action(self, name, callback, shortcuts=None):
        """Add an application action.

        Args:
            name: the name of the action
            callback: the function to be called when the action is
              activated
            shortcuts: an optional list of accelerators
        """
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)


def main(version):
    """The application's entry point."""
    app = SwalletApplication()
    return app.run(sys.argv)
