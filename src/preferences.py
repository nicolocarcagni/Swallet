import os
import json
from gi.repository import Adw, Gtk, GLib

@Gtk.Template(resource_path='/io/github/nicolocarcagni/Swallet/preferences.ui')
class PreferencesWindow(Adw.PreferencesWindow):
    __gtype_name__ = 'PreferencesWindow'

    entry_node_url = Gtk.Template.Child()

    def __init__(self, api_client, **kwargs):
        super().__init__(**kwargs)
        self.api_client = api_client
        self.config_path = os.path.join(GLib.get_user_data_dir(), "swallet_config.json")
        self._load_config()

    def _load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                    url = config.get("node_url", "https://sole.nicolocarcagni.dev")
                    self.entry_node_url.set_text(url)
                    self.api_client.set_node(url)
            except Exception as e:
                print(f"Failed to load config: {e}")
                self.entry_node_url.set_text("https://sole.nicolocarcagni.dev")
        else:
            self.entry_node_url.set_text("https://sole.nicolocarcagni.dev")
            
    def _save_config(self, url: str):
        try:
            with open(self.config_path, 'w') as f:
                json.dump({"node_url": url}, f)
        except Exception as e:
            print(f"Failed to save config: {e}")

    @Gtk.Template.Callback()
    def on_url_changed(self, entry):
        url = entry.get_text()
        self.api_client.set_node(url)
        self._save_config(url)
