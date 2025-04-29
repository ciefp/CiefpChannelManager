import os
import shutil
import zipfile
import requests
from enigma import eListboxPythonMultiContent, eTimer
from Components.Pixmap import Pixmap
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Plugins.Plugin import PluginDescriptor
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Tools.Directories import fileExists
from enigma import eDVBDB

PLUGIN_VERSION = "1.5"
PLUGIN_ICON = "icon.png"
PLUGIN_NAME = "CiefpChannelManager"
TMP_DOWNLOAD = "/tmp/ciefp-E2-75E-34W"
TMP_SELECTED = "/tmp/CiefpChannelManager"
PLUGIN_DESCRIPTION = "Manage Bouquets and Channels Plugin"
GITHUB_API_URL = "https://api.github.com/repos/ciefp/ciefpsettings-enigma2-zipped/contents/"
PLUGIN_VERSION_URL = "https://raw.githubusercontent.com/ciefp/CiefpChannelManager/refs/heads/main/version.txt"
INSTALLER_URL = "https://raw.githubusercontent.com/ciefp/CiefpChannelManager/main/installer.sh"
STATIC_NAMES = ["ciefp-E2-75E-34W"]

class CiefpChannelEditor(Screen):
    skin = """
        <screen position="center,center" size="1200,800" title="..:: Ciefp Channel Editor ::..">
            <widget name="channel_list" position="0,0" size="700,700" scrollbarMode="showOnDemand" itemHeight="33" font="Regular;28" />
            <widget name="background" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/CiefpChannelManager/background3.png" position="700,0" size="500,800" />
            <widget name="status" position="0,710" size="700,50" font="Regular;24" />
            <widget name="red_button" position="0,750" size="150,35" font="Bold;28" halign="center" backgroundColor="#9F1313" foregroundColor="#000000" />
            <widget name="green_button" position="170,750" size="150,35" font="Bold;28" halign="center" backgroundColor="#1F771F" foregroundColor="#000000" />
            <widget name="yellow_button" position="340,750" size="150,35" font="Bold;28" halign="center" backgroundColor="#9F9F13" foregroundColor="#000000" />
            <widget name="blue_button" position="510,750" size="150,35" font="Bold;28" halign="center" backgroundColor="#1F1F77" foregroundColor="#000000" />
        </screen>
    """

    def __init__(self, session, bouquet_file):
        Screen.__init__(self, session)
        self.session = session
        self.bouquet_file = bouquet_file
        self.channel_list = []
        self.channel_refs = {}
        self.selected_channels = []
        self.marked_channels = []
        self.move_mode = False
        self.current_index = 0
        self.bouquet_name = None
        self["channel_list"] = MenuList([])
        self["background"] = Pixmap()
        self["status"] = Label("Loading channels...")
        self["red_button"] = Label("Delete")
        self["green_button"] = Label("Save")
        self["yellow_button"] = Label("Move Mode")
        self["blue_button"] = Label("Select Group")
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "DirectionActions"], {
            "ok": self.select_channel,
            "cancel": self.exit,
            "up": self.navigate_or_move_up,
            "down": self.navigate_or_move_down,
            "red": self.delete_selected,
            "green": self.save_settings,
            "yellow": self.toggle_move_mode,
            "blue": self.select_group,
        }, -1)
        self.onLayoutFinish.append(self.load_channels)

    def load_channels(self):
        self.channel_list = []
        self.channel_refs = {}
        self.bouquet_name = None
        lamedb_services = self.parse_lamedb()
        bouquet_path = os.path.join("/etc/enigma2", self.bouquet_file)

        debug_file = "/tmp/channel_editor_debug.log"
        with open(debug_file, 'a') as df:
            df.write(f"Loading bouquet: {bouquet_path}\n")
            df.write(f"lamedb_services keys: {list(lamedb_services.keys())[:5]}...\n")

        if not os.path.exists(bouquet_path):
            self["status"].setText(f"Error: Bouquet file {self.bouquet_file} not found!")
            return

        try:
            with open(bouquet_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                i = 0
                while i < len(lines):
                    line = lines[i].strip()
                    if not line:
                        i += 1
                        continue
                    if line.startswith("#NAME"):
                        self.bouquet_name = line
                        with open(debug_file, 'a') as df:
                            df.write(f"Bouquet name: {self.bouquet_name}\n")
                        i += 1
                    elif line.startswith("#SERVICE"):
                        parts = line.split(":")
                        if len(parts) >= 10:
                            if parts[1] == "64":
                                with open(debug_file, 'a') as df:
                                    df.write(f"Ignoring marker service: {line}\n")
                                i += 1
                                continue
                            if parts[0] == "#SERVICE 4097" and parts[1] == "0" and parts[2] == "2":
                                with open(debug_file, 'a') as df:
                                    df.write(f"Ignoring IPTV service (4097:0:2): {line}\n")
                                i += 1
                                if i < len(lines) and lines[i].strip().startswith("#DESCRIPTION"):
                                    i += 1
                                continue
                            if parts[0] == "#SERVICE 4097" and parts[1] == "0" and parts[2] == "1":
                                channel_name = "Unknown IPTV"
                                if i + 1 < len(lines):
                                    next_line = lines[i + 1].strip()
                                    if next_line.startswith("#DESCRIPTION"):
                                        channel_name = next_line.replace("#DESCRIPTION", "").strip()
                                        i += 1
                                self.channel_list.append(channel_name)
                                self.channel_refs[channel_name] = line
                                with open(debug_file, 'a') as df:
                                    df.write(f"IPTV channel: {channel_name}, Service: {line}\n")
                                i += 1
                                continue
                            sid = parts[3]
                            tsid = parts[4]
                            onid = parts[5]
                            satfreq = parts[6].lower()
                            satfreq = f"00{satfreq}" if len(satfreq) == 6 else satfreq.zfill(8)
                            search_keys = [
                                f"{int(sid, 16):04x}:{satfreq}:{int(tsid, 16):04x}:{int(onid, 16):04x}",
                                f"{sid.lower()}:{satfreq}:{tsid.lower()}:{onid.lower()}",
                                f"{int(sid, 16):04x}:{satfreq[2:]}:{int(tsid, 16):04x}:{int(onid, 16):04x}",
                            ]
                            channel_name = None
                            for search_key in search_keys:
                                channel_name = lamedb_services.get(search_key)
                                if channel_name:
                                    break
                            if not channel_name:
                                channel_name = f"Unknown ({search_keys[0]})"
                            self.channel_list.append(channel_name)
                            self.channel_refs[channel_name] = line
                            with open(debug_file, 'a') as df:
                                df.write(f"Bouquet service: {line}\n")
                                df.write(f"Search keys: {search_keys}\n")
                                df.write(f"Channel name: {channel_name}\n")
                        i += 1
                    elif line.startswith("#DESCRIPTION"):
                        marker_name = line.replace("#DESCRIPTION", "").strip()
                        self.channel_list.append(marker_name)
                        self.channel_refs[marker_name] = line
                        with open(debug_file, 'a') as df:
                            df.write(f"Marker: {marker_name}\n")
                        i += 1
                    else:
                        i += 1

            if not self.channel_list:
                self["status"].setText("No channels or markers found in bouquet!")
                return

            self["channel_list"].setList(self.channel_list)
            self["status"].setText("Channels loaded successfully.")
            self.current_index = 0
            self["channel_list"].moveToIndex(self.current_index)
        except Exception as e:
            self["status"].setText(f"Error loading channels: {str(e)}")
            with open(debug_file, 'a') as df:
                df.write(f"Error loading channels: {str(e)}\n")

    def parse_lamedb(self):
        lamedb_path = "/etc/enigma2/lamedb"
        services = {}

        if not os.path.exists(lamedb_path):
            self["status"].setText("Error: lamedb file not found!")
            return services

        try:
            with open(lamedb_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                in_services = False
                current_key = None
                for line in lines:
                    line = line.strip()
                    if line == "services":
                        in_services = True
                        continue
                    elif line == "end":
                        in_services = False
                        continue
                    if in_services:
                        if ":" in line and not line.startswith("p:"):
                            parts = line.split(":")
                            if len(parts) >= 4:
                                sid = parts[0]
                                satfreq = parts[1].lower()
                                tsid = parts[2]
                                onid = parts[3]
                                services[f"{sid}:{satfreq}:{tsid}:{onid}"] = None
                                services[f"{sid.lstrip('0')}:{satfreq}:{tsid.lstrip('0')}:{onid.lstrip('0')}"] = None
                                services[f"{sid}:{satfreq[2:]}:{tsid}:{onid}"] = None
                                current_key = f"{sid}:{satfreq}:{tsid}:{onid}"
                        elif current_key and line and not line.startswith("p:"):
                            services[current_key] = line
                            sid, satfreq, tsid, onid = current_key.split(":")
                            services[f"{sid.lstrip('0')}:{satfreq}:{tsid.lstrip('0')}:{onid.lstrip('0')}"] = line
                            services[f"{sid}:{satfreq[2:]}:{tsid}:{onid}"] = line
                            current_key = None
        except Exception as e:
            self["status"].setText(f"Error parsing lamedb: {str(e)}")
            with open(debug_file, 'a') as df:
                df.write(f"Error parsing lamedb: {str(e)}\n")
        return services

    def select_channel(self):
        current = self["channel_list"].getCurrent()
        if not current:
            return
        clean_current = current.lstrip(">> ").lstrip("+ ")
        debug_file = "/tmp/channel_editor_debug.log"
        with open(debug_file, 'a') as df:
            df.write(f"Selecting channel: {current}, Clean: {clean_current}, Move mode: {self.move_mode}\n")
        if self.move_mode:
            if clean_current in self.selected_channels:
                self.selected_channels.remove(clean_current)
            else:
                self.selected_channels.append(clean_current)
            with open(debug_file, 'a') as df:
                df.write(f"Selected channels: {self.selected_channels}\n")
        else:
            if clean_current in self.marked_channels:
                self.marked_channels.remove(clean_current)
            else:
                self.marked_channels.append(clean_current)
            with open(debug_file, 'a') as df:
                df.write(f"Marked channels: {self.marked_channels}\n")
        self.update_list()

    def toggle_move_mode(self):
        self.move_mode = not self.move_mode
        self["yellow_button"].setText("Disable Move" if self.move_mode else "Move Mode")
        self["status"].setText("Move Mode enabled" if self.move_mode else "Move Mode disabled")
        if self.move_mode:
            self.selected_channels = self.marked_channels[:]
        else:
            self.selected_channels = []
            self.marked_channels = []
        debug_file = "/tmp/channel_editor_debug.log"
        with open(debug_file, 'a') as df:
            df.write(f"Toggle move mode: move_mode={self.move_mode}, selected_channels={self.selected_channels}, marked_channels={self.marked_channels}\n")
        self.update_list()

    def delete_selected(self):
        debug_file = "/tmp/channel_editor_debug.log"
        channels_to_delete = self.selected_channels if self.move_mode else self.marked_channels
        if not channels_to_delete:
            self.session.open(
                MessageBox,
                "No channels or markers selected to delete.",
                MessageBox.TYPE_INFO,
                timeout=5
            )
            with open(debug_file, 'a') as df:
                df.write(f"No channels to delete. Selected: {self.selected_channels}, Marked: {self.marked_channels}\n")
            return
        with open(debug_file, 'a') as df:
            df.write(f"Deleting channels: {channels_to_delete}\n")
        self.channel_list = [ch for ch in self.channel_list if ch not in channels_to_delete]
        for ch in channels_to_delete:
            if ch in self.channel_refs:
                del self.channel_refs[ch]
        self.selected_channels = []
        self.marked_channels = []
        self.update_list()
        if not self.channel_list:
            self["status"].setText("No channels or markers left in bouquet!")
        else:
            self["status"].setText(f"Deleted {len(channels_to_delete)} items.")
        with open(debug_file, 'a') as df:
            df.write(f"After deletion, channel_list: {self.channel_list[:5]}...\n")

    def select_group(self):
        current = self["channel_list"].getCurrent()
        if not current:
            return
        clean_current = current.lstrip(">> ").lstrip("+ ")
        debug_file = "/tmp/channel_editor_debug.log"
        if clean_current not in self.channel_refs or not self.channel_refs[clean_current].startswith("#DESCRIPTION"):
            self.session.open(
                MessageBox,
                "Please select a marker first.",
                MessageBox.TYPE_INFO,
                timeout=5
            )
            return
        start_idx = self.channel_list.index(clean_current)
        group = [clean_current]
        for i in range(start_idx + 1, len(self.channel_list)):
            ch = self.channel_list[i]
            if ch in self.channel_refs and self.channel_refs[ch].startswith("#DESCRIPTION"):
                break
            group.append(ch)
        self.selected_channels = group
        self.marked_channels = group
        with open(debug_file, 'a') as df:
            df.write(f"Selected group: {group}\n")
        self["status"].setText(f"Selected group: {len(group)} items.")
        self.update_list()

    def update_list(self):
        display_list = []
        for channel in self.channel_list:
            prefix = ""
            if self.move_mode and channel in self.selected_channels:
                prefix = ">> "
            elif channel in self.marked_channels:
                prefix = "+ "
            display_list.append(prefix + channel)
        debug_file = "/tmp/channel_editor_debug.log"
        with open(debug_file, 'a') as df:
            df.write(f"Updating list, display_list: {display_list[:5]}...\n")
        self["channel_list"].setList(display_list)
        self["channel_list"].moveToIndex(self.current_index)

    def navigate_or_move_up(self):
        if self.move_mode and self.selected_channels:
            new_list = self.channel_list[:]
            moved = False
            selected_indices = [new_list.index(channel) for channel in self.selected_channels if channel in new_list]
            if not selected_indices:
                return
            min_idx = min(selected_indices)
            if min_idx == 0:
                return
            selected_group = [new_list[i] for i in sorted(selected_indices)]
            for idx in sorted(selected_indices, reverse=True):
                new_list.pop(idx)
            insert_idx = min_idx - 1
            for channel in selected_group:
                new_list.insert(insert_idx, channel)
                insert_idx += 1
                moved = True
            if self.current_index in selected_indices:
                self.current_index -= 1
            elif self.current_index > min_idx:
                self.current_index -= len(selected_indices)
            if moved:
                self.channel_list = new_list
                self.update_list()
        else:
            if self.current_index > 0:
                self.current_index -= 1
                self["channel_list"].moveToIndex(self.current_index)

    def navigate_or_move_down(self):
        if self.move_mode and self.selected_channels:
            new_list = self.channel_list[:]
            moved = False
            selected_indices = [new_list.index(channel) for channel in self.selected_channels if channel in new_list]
            if not selected_indices:
                return
            max_idx = max(selected_indices)
            if max_idx == len(new_list) - 1:
                return
            selected_group = [new_list[i] for i in sorted(selected_indices)]
            for idx in sorted(selected_indices, reverse=True):
                new_list.pop(idx)
            insert_idx = max_idx + 1 - len(selected_indices) + 1
            for channel in selected_group:
                new_list.insert(insert_idx, channel)
                insert_idx += 1
                moved = True
            if self.current_index in selected_indices:
                self.current_index += 1
            elif self.current_index >= max_idx - len(selected_indices) + 1:
                self.current_index += len(selected_indices)
            if moved:
                self.channel_list = new_list
                self.update_list()
        else:
            if self.current_index < len(self.channel_list) - 1:
                self.current_index += 1
                self["channel_list"].moveToIndex(self.current_index)

    def save_settings(self):
        if not self.channel_list:
            self["status"].setText("No channels to save!")
            return
        bouquet_path = os.path.join("/etc/enigma2", self.bouquet_file)
        try:
            new_lines = []
            if self.bouquet_name:
                new_lines.append(self.bouquet_name + "\n")
            for channel in self.channel_list:
                line = self.channel_refs.get(channel)
                if line:
                    new_lines.append(line + "\n")
                    if line.startswith("#SERVICE 4097:0:1"):
                        new_lines.append(f"#DESCRIPTION {channel}\n")
            debug_file = "/tmp/channel_editor_debug.log"
            with open(debug_file, 'a') as df:
                df.write(f"Saving bouquet: {bouquet_path}\n")
                df.write(f"Bouquet name: {self.bouquet_name}\n")
                df.write(f"Lines to save: {new_lines[:5]}...\n")
            with open(bouquet_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            self.reload_settings()
            self["status"].setText("Settings saved successfully!")
        except Exception as e:
            self["status"].setText(f"Error saving settings: {str(e)}")
            with open(debug_file, 'a') as df:
                df.write(f"Error saving settings: {str(e)}\n")

    def reload_settings(self):
        try:
            eDVBDB.getInstance().reloadServicelist()
            eDVBDB.getInstance().reloadBouquets()
            self.session.open(
                MessageBox,
                "Settings saved and reloaded successfully!",
                MessageBox.TYPE_INFO,
                timeout=5
            )
        except Exception as e:
            self.session.open(
                MessageBox,
                f"Reload failed: {str(e)}",
                MessageBox.TYPE_ERROR,
                timeout=5
            )

    def exit(self):
        self.close()

class CiefpBouquetEditor(Screen):
    skin = """
        <screen position="center,center" size="1200,800" title="..:: Ciefp Bouquet Editor ::..">
            <widget name="bouquet_list" position="0,0" size="700,700" scrollbarMode="showOnDemand" itemHeight="33" font="Regular;28" />
            <widget name="background" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/CiefpChannelManager/background2.png" position="700,0" size="500,800" />
            <widget name="status" position="0,710" size="700,50" font="Regular;24" />
            <widget name="red_button" position="0,750" size="150,35" font="Bold;28" halign="center" backgroundColor="#9F1313" foregroundColor="#000000" />
            <widget name="green_button" position="170,750" size="150,35" font="Bold;28" halign="center" backgroundColor="#1F771F" foregroundColor="#000000" />
            <widget name="yellow_button" position="340,750" size="150,35" font="Bold;28" halign="center" backgroundColor="#9F9F13" foregroundColor="#000000" />
            <widget name="blue_button" position="510,750" size="150,35" font="Bold;28" halign="center" backgroundColor="#1F1F77" foregroundColor="#000000" />
        </screen>
    """

    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session
        self.bouquet_list = []
        self.bouquet_names = {}
        self.selected_bouquets = []
        self.move_mode = False
        self.current_index = 0
        self["bouquet_list"] = MenuList([])
        self["background"] = Pixmap()
        self["status"] = Label("Loading bouquets...")
        self["red_button"] = Label("Delete")
        self["green_button"] = Label("Save")
        self["yellow_button"] = Label("Move Mode")
        self["blue_button"] = Label("Channels")
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "DirectionActions"], {
            "ok": self.toggle_selection,
            "cancel": self.exit,
            "up": self.navigate_or_move_up,
            "down": self.navigate_or_move_down,
            "red": self.delete_selected_bouquets,
            "green": self.save_settings,
            "yellow": self.toggle_move_mode,
            "blue": self.open_channel_editor,
        }, -1)
        self.onLayoutFinish.append(self.load_bouquets)

    def load_bouquets(self):
        self.bouquet_names = {}
        bouquets_file = "/etc/enigma2/bouquets.tv"
        bouquet_order = []
        bouquet_display_list = []
        name_to_file = {}
        debug_file = "/tmp/channel_editor_debug.log"

        with open(debug_file, 'a') as df:
            df.write(f"Loading bouquets from: {bouquets_file}\n")

        if fileExists(bouquets_file):
            with open(bouquets_file, 'r', encoding='utf-8') as file:
                for line in file:
                    if "FROM BOUQUET" in line:
                        start = line.find('"') + 1
                        end = line.find('"', start)
                        if start != -1 and end != -1:
                            bouquet_file = line[start:end]
                            bouquet_order.append(bouquet_file)
                            with open(debug_file, 'a') as df:
                                df.write(f"Found bouquet file: {bouquet_file}\n")
        else:
            self["status"].setText("Error: bouquets.tv not found!")
            with open(debug_file, 'a') as df:
                df.write("Error: bouquets.tv not found!\n")
            return

        for bouquet_file in bouquet_order:
            file_path = os.path.join("/etc/enigma2", bouquet_file)
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        first_line = f.readline().strip()
                        if first_line.startswith("#NAME"):
                            display_name = first_line.replace("#NAME", "", 1).strip()
                            self.bouquet_names[display_name] = bouquet_file
                            name_to_file[bouquet_file] = display_name
                            with open(debug_file, 'a') as df:
                                df.write(f"Loaded bouquet: {display_name} -> {bouquet_file}\n")
                except Exception as e:
                    self["status"].setText(f"Error reading {bouquet_file}: {str(e)}")
                    with open(debug_file, 'a') as df:
                        df.write(f"Error reading {bouquet_file}: {str(e)}\n")
                    return

        for bouquet_file in bouquet_order:
            if bouquet_file in name_to_file:
                bouquet_display_list.append(name_to_file[bouquet_file])

        if not bouquet_display_list:
            self["status"].setText("No valid bouquet files found!")
            with open(debug_file, 'a') as df:
                df.write("No valid bouquet files found!\n")
            return

        self.bouquet_list = bouquet_display_list
        self["bouquet_list"].setList(bouquet_display_list)
        self["status"].setText("Bouquets loaded successfully.")
        self.current_index = 0
        self["bouquet_list"].moveToIndex(self.current_index)
        with open(debug_file, 'a') as df:
            df.write(f"Bouquet list: {bouquet_display_list}\n")
            df.write("Bouquets loaded successfully.\n")

    def toggle_selection(self):
        if not self.bouquet_list:
            return
        current_bouquet = self.bouquet_list[self.current_index]
        if current_bouquet in self.selected_bouquets:
            self.selected_bouquets.remove(current_bouquet)
        else:
            self.selected_bouquets.append(current_bouquet)
        debug_file = "/tmp/channel_editor_debug.log"
        with open(debug_file, 'a') as df:
            df.write(f"Toggle selection: {current_bouquet}, Selected bouquets: {self.selected_bouquets}\n")
        self.update_list()

    def delete_selected_bouquets(self):
        debug_file = "/tmp/channel_editor_debug.log"
        if not self.selected_bouquets:
            self.session.open(
                MessageBox,
                "No bouquets selected to delete.",
                MessageBox.TYPE_INFO,
                timeout=5
            )
            with open(debug_file, 'a') as df:
                df.write(f"No bouquets to delete. Selected: {self.selected_bouquets}\n")
            return
        with open(debug_file, 'a') as df:
            df.write(f"Deleting bouquets: {self.selected_bouquets}\n")
        bouquets_to_delete = self.selected_bouquets[:]
        for bouquet in bouquets_to_delete:
            bouquet_file = self.bouquet_names.get(bouquet)
            if bouquet_file:
                file_path = os.path.join("/etc/enigma2", bouquet_file)
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        with open(debug_file, 'a') as df:
                            df.write(f"Deleted file: {file_path}\n")
                    except Exception as e:
                        self["status"].setText(f"Error deleting {bouquet_file}: {str(e)}")
                        with open(debug_file, 'a') as df:
                            df.write(f"Error deleting {bouquet_file}: {str(e)}\n")
                        return
        self.bouquet_list = [bq for bq in self.bouquet_list if bq not in bouquets_to_delete]
        self.selected_bouquets = []
        self.bouquet_names = {name: file for name, file in self.bouquet_names.items() if name in self.bouquet_list}
        self.update_list()
        if not self.bouquet_list:
            self["status"].setText("No bouquets left!")
        else:
            self["status"].setText(f"Deleted {len(bouquets_to_delete)} bouquets.")
        with open(debug_file, 'a') as df:
            df.write(f"After deletion, bouquet_list: {self.bouquet_list[:5]}...\n")

    def toggle_move_mode(self):
        self.move_mode = not self.move_mode
        self["yellow_button"].setText("Disable Move" if self.move_mode else "Move Mode")
        self["status"].setText("Move Mode enabled" if self.move_mode else "Move Mode disabled")
        if not self.move_mode:
            self.selected_bouquets = []
        debug_file = "/tmp/channel_editor_debug.log"
        with open(debug_file, 'a') as df:
            df.write(f"Toggle move mode: move_mode={self.move_mode}, selected_bouquets={self.selected_bouquets}\n")
        self.update_list()

    def update_list(self):
        display_list = []
        for bouquet in self.bouquet_list:
            prefix = ""
            if self.move_mode and bouquet in self.selected_bouquets:
                prefix = ">> "
            elif bouquet in self.selected_bouquets:
                prefix = "+ "
            display_list.append(prefix + bouquet)
        debug_file = "/tmp/channel_editor_debug.log"
        with open(debug_file, 'a') as df:
            df.write(f"Updating list, display_list: {display_list[:5]}...\n")
        self["bouquet_list"].setList(display_list)
        self["bouquet_list"].moveToIndex(self.current_index)

    def navigate_or_move_up(self):
        if self.move_mode and self.selected_bouquets:
            new_list = self.bouquet_list[:]
            moved = False
            selected_indices = [new_list.index(bouquet) for bouquet in self.selected_bouquets if bouquet in new_list]
            if not selected_indices:
                return
            min_idx = min(selected_indices)
            if min_idx == 0:
                return
            selected_group = [new_list[i] for i in sorted(selected_indices)]
            for idx in sorted(selected_indices, reverse=True):
                new_list.pop(idx)
            insert_idx = min_idx - 1
            for bouquet in selected_group:
                new_list.insert(insert_idx, bouquet)
                insert_idx += 1
                moved = True
            if self.current_index in selected_indices:
                self.current_index -= 1
            elif self.current_index > min_idx:
                self.current_index -= len(selected_indices)
            if moved:
                self.bouquet_list = new_list
                self.update_list()
        else:
            if self.current_index > 0:
                self.current_index -= 1
                self["bouquet_list"].moveToIndex(self.current_index)

    def navigate_or_move_down(self):
        if self.move_mode and self.selected_bouquets:
            new_list = self.bouquet_list[:]
            moved = False
            selected_indices = [new_list.index(bouquet) for bouquet in self.selected_bouquets if bouquet in new_list]
            if not selected_indices:
                return
            max_idx = max(selected_indices)
            if max_idx == len(new_list) - 1:
                return
            selected_group = [new_list[i] for i in sorted(selected_indices)]
            for idx in sorted(selected_indices, reverse=True):
                new_list.pop(idx)
            insert_idx = max_idx + 1 - len(selected_indices) + 1
            for bouquet in selected_group:
                new_list.insert(insert_idx, bouquet)
                insert_idx += 1
                moved = True
            if self.current_index in selected_indices:
                self.current_index += 1
            elif self.current_index >= max_idx - len(selected_indices) + 1:
                self.current_index += len(selected_indices)
            if moved:
                self.bouquet_list = new_list
                self.update_list()
        else:
            if self.current_index < len(self.bouquet_list) - 1:
                self.current_index += 1
                self["bouquet_list"].moveToIndex(self.current_index)

    def save_settings(self):
        if not self.bouquet_list:
            self["status"].setText("No bouquets to save!")
            return
        bouquets_file = "/etc/enigma2/bouquets.tv"
        debug_file = "/tmp/channel_editor_debug.log"
        try:
            with open(bouquets_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            new_lines = []
            bouquet_lines = []
            for line in lines:
                if "FROM BOUQUET" in line:
                    bouquet_lines.append(line)
                else:
                    new_lines.append(line)
            for bouquet_name in self.bouquet_list:
                bouquet_file = self.bouquet_names.get(bouquet_name)
                if bouquet_file:
                    for line in bouquet_lines:
                        if bouquet_file in line:
                            new_lines.append(line)
                            break
            with open(bouquets_file, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            with open(debug_file, 'a') as df:
                df.write(f"Saved bouquets to {bouquets_file}\n")
            self.reload_settings()
            self["status"].setText("Settings saved successfully!")
        except Exception as e:
            self["status"].setText(f"Error saving settings: {str(e)}")
            with open(debug_file, 'a') as df:
                df.write(f"Error saving settings: {str(e)}\n")

    def reload_settings(self):
        try:
            eDVBDB.getInstance().reloadServicelist()
            eDVBDB.getInstance().reloadBouquets()
            self.session.open(
                MessageBox,
                "Settings saved and reloaded successfully!",
                MessageBox.TYPE_INFO,
                timeout=5
            )
        except Exception as e:
            self.session.open(
                MessageBox,
                f"Reload failed: {str(e)}",
                MessageBox.TYPE_ERROR,
                timeout=5
            )

    def open_channel_editor(self):
        current = self["bouquet_list"].getCurrent()
        if current:
            current = current.lstrip(">> ").lstrip("+ ")
            bouquet_file = self.bouquet_names.get(current)
            if bouquet_file:
                self.session.open(CiefpChannelEditor, bouquet_file)
            else:
                self.session.open(
                    MessageBox,
                    "Error: Selected bouquet file not found.",
                    MessageBox.TYPE_ERROR,
                    timeout=5
                )
        else:
            self.session.open(
                MessageBox,
                "Please select a bouquet first.",
                MessageBox.TYPE_INFO,
                timeout=5
            )

    def exit(self):
        self.close()

class CiefpChannelManager(Screen):
    skin = """
        <screen position="center,center" size="1600,800" title="..:: Ciefp Bouquet Updater ::..    (Version {version})">
            <widget name="left_list" position="0,0" size="620,700" scrollbarMode="showOnDemand" itemHeight="33" font="Regular;28" />
            <widget name="right_list" position="630,0" size="610,700" scrollbarMode="showOnDemand" itemHeight="33" font="Regular;28" />
            <widget name="background" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/CiefpChannelManager/background.png" position="1240,0" size="360,800" />
            <widget name="status" position="0,710" size="840,50" font="Regular;24" />
            <widget name="red_button" position="0,750" size="150,35" font="Bold;28" halign="center" backgroundColor="#9F1313" foregroundColor="#000000" />
            <widget name="green_button" position="170,750" size="150,35" font="Bold;28" halign="center" backgroundColor="#1F771F" foregroundColor="#000000" />
            <widget name="yellow_button" position="340,750" size="150,35" font="Bold;28" halign="center" backgroundColor="#9F9F13" foregroundColor="#000000" />
            <widget name="blue_button" position="510,750" size="150,35" font="Bold;28" halign="center" backgroundColor="#1F1F77" foregroundColor="#000000" />
            <widget name="version_info" position="680,750" size="560,40" font="Regular;20" foregroundColor="#FFFFFF" />
        </screen>
    """.format(version=PLUGIN_VERSION)

    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session
        self.selected_bouquets = []
        self.bouquet_names = {}
        self.latest_version = None
        self["left_list"] = MenuList([])
        self["right_list"] = MenuList([])
        self["background"] = Pixmap()
        self["status"] = Label("Loading bouquets...")
        self["red_button"] = Label("Exit")
        self["green_button"] = Label("Copy")
        self["yellow_button"] = Label("Install")
        self["blue_button"] = Label("Editor")
        self["version_info"] = Label("")
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
            "ok": self.select_item,
            "cancel": self.exit,
            "up": self.up,
            "down": self.down,
            "red": self.exit,
            "green": self.copy_files,
            "yellow": self.install,
            "blue": self.open_bouquet_editor,
        }, -1)
        self.onLayoutFinish.append(self.check_plugin_version)
        self.onLayoutFinish.append(self.fetch_list_version_info)
        self.download_settings()
        self.load_bouquets()

    def check_plugin_version(self):
        debug_file = "/tmp/channel_editor_debug.log"
        try:
            response = requests.get(PLUGIN_VERSION_URL)
            response.raise_for_status()
            self.latest_version = response.text.strip()
            with open(debug_file, 'a') as df:
                df.write(f"Plugin version check: Current={PLUGIN_VERSION}, Latest={self.latest_version}\n")
            if self.latest_version != PLUGIN_VERSION:
                self.setTitle(f"..:: Ciefp Bouquet Updater ::.. (Version {PLUGIN_VERSION}) (Update available: {self.latest_version})")
                # Odlaganje prikaza MessageBox-a
                self.upgrade_timer = eTimer()
                self.upgrade_timer.callback.append(self.show_upgrade_prompt)
                self.upgrade_timer.start(1000, True)  # 1 sekunda odlaganja
            else:
                self.setTitle(f"..:: Ciefp Bouquet Updater ::.. (Version {PLUGIN_VERSION})")
        except Exception as e:
            with open(debug_file, 'a') as df:
                df.write(f"Error checking plugin version: {str(e)}\n")
            self.setTitle(f"..:: Ciefp Bouquet Updater ::.. (Version {PLUGIN_VERSION})")

    def show_upgrade_prompt(self):
        debug_file = "/tmp/channel_editor_debug.log"
        with open(debug_file, 'a') as df:
            df.write(f"Showing upgrade prompt for version: {self.latest_version}\n")
        if self.latest_version and self.latest_version != PLUGIN_VERSION:
            self.session.openWithCallback(
                self.confirm_upgrade,
                MessageBox,
                f"A new version ({self.latest_version}) is available. Would you like to upgrade the plugin now?",
                MessageBox.TYPE_YESNO
            )

    def confirm_upgrade(self, result):
        if result:
            self.upgrade_plugin()

    def upgrade_plugin(self):
        debug_file = "/tmp/channel_editor_debug.log"
        try:
            cmd = f"wget -q --no-check-certificate {INSTALLER_URL} -O - | /bin/sh"
            result = os.system(cmd)
            with open(debug_file, 'a') as df:
                df.write(f"Plugin upgrade executed: Command={cmd}, Result={result}\n")
            if result == 0:
                self.session.open(
                    MessageBox,
                    "Plugin upgrade completed successfully. Please restart the plugin or Enigma2 to apply changes.",
                    MessageBox.TYPE_INFO,
                    timeout=10
                )
            else:
                self.session.open(
                    MessageBox,
                    f"Plugin upgrade failed with error code: {result}. Check logs for details.",
                    MessageBox.TYPE_ERROR,
                    timeout=10
                )
        except Exception as e:
            with open(debug_file, 'a') as df:
                df.write(f"Error during plugin upgrade: {str(e)}\n")
            self.session.open(
                MessageBox,
                f"Error during plugin upgrade: {str(e)}",
                MessageBox.TYPE_ERROR,
                timeout=10
            )

    def fetch_list_version_info(self):
        debug_file = "/tmp/channel_editor_debug.log"
        try:
            response = requests.get(GITHUB_API_URL)
            response.raise_for_status()
            files = response.json()
            for file in files:
                if any(name in file["name"] for name in STATIC_NAMES) and file["name"].endswith(".zip"):
                    version_with_date = file["name"].replace(".zip", "")
                    self["version_info"].setText(f"List: {version_with_date}")
                    with open(debug_file, 'a') as df:
                        df.write(f"List version fetched: {version_with_date}\n")
                    return
            self["version_info"].setText("List: (Date not available)")
        except Exception as e:
            with open(debug_file, 'a') as df:
                df.write(f"Error fetching list version: {str(e)}\n")
            self["version_info"].setText("List: (Error fetching date)")

    def open_bouquet_editor(self):
        self.session.open(CiefpBouquetEditor)

    def download_settings(self):
        self["status"].setText("Fetching file list from GitHub...")
        try:
            response = requests.get(GITHUB_API_URL)
            response.raise_for_status()
            files = response.json()
            zip_url = None
            for file in files:
                if any(name in file["name"] for name in STATIC_NAMES) and file["name"].endswith(".zip"):
                    zip_url = file["download_url"]
                    break
            if not zip_url:
                raise Exception("No matching ZIP file found on GitHub.")
            self["status"].setText("Downloading settings from GitHub...")
            zip_path = os.path.join("/tmp", "latest.zip")
            zip_response = requests.get(zip_url)
            with open(zip_path, 'wb') as f:
                f.write(zip_response.content)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                temp_extract_path = "/tmp/temp_extract"
                if not os.path.exists(temp_extract_path):
                    os.makedirs(temp_extract_path)
                zip_ref.extractall(temp_extract_path)
                extracted_root = os.path.join(temp_extract_path, os.listdir(temp_extract_path)[0])
                if os.path.exists(TMP_DOWNLOAD):
                    shutil.rmtree(TMP_DOWNLOAD)
                shutil.move(extracted_root, TMP_DOWNLOAD)
            self["status"].setText("Settings downloaded and extracted successfully.")
            self.parse_satellites()
        except Exception as e:
            self["status"].setText(f"Error: {str(e)}")

    def parse_satellites(self):
        pass

    def load_bouquets(self):
        self.bouquet_names = {}
        bouquet_dir = TMP_DOWNLOAD
        bouquets_file = os.path.join(bouquet_dir, "bouquets.tv")

        if not os.path.exists(bouquet_dir):
            self["status"].setText("Error: Temporary directory not found!")
            return

        bouquet_order = []
        if fileExists(bouquets_file):
            with open(bouquets_file, 'r', encoding='utf-8') as file:
                for line in file:
                    if "FROM BOUQUET" in line:
                        start = line.find('"') + 1
                        end = line.find('"', start)
                        if start != -1 and end != -1:
                            bouquet_file = line[start:end]
                            bouquet_order.append(bouquet_file)
        else:
            self["status"].setText("Error: bouquets.tv not found!")
            return

        bouquet_display_list = []
        name_to_file = {}

        for bouquet_file in bouquet_order:
            file_path = os.path.join(bouquet_dir, bouquet_file)
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        first_line = f.readline().strip()
                        if first_line.startswith("#NAME"):
                            display_name = first_line.replace("#NAME", "", 1).strip()
                            self.bouquet_names[first_line] = bouquet_file
                            name_to_file[bouquet_file] = display_name
                except Exception as e:
                    self["status"].setText(f"Error reading {bouquet_file}: {str(e)}")
                    return

        for bouquet_file in bouquet_order:
            if bouquet_file in name_to_file:
                bouquet_display_list.append(name_to_file[bouquet_file])

        if not bouquet_display_list:
            self["status"].setText("No valid bouquet files found!")
            return

        self["left_list"].setList(bouquet_display_list)
        self["status"].setText("Bouquets loaded successfully.")

    def select_item(self):
        selected_name = self["left_list"].getCurrent()
        if selected_name:
            if selected_name in self.selected_bouquets:
                self.selected_bouquets.remove(selected_name)
            else:
                self.selected_bouquets.append(selected_name)
            self["right_list"].setList(self.selected_bouquets)

    def copy_files(self):
        if not self.selected_bouquets:
            self["status"].setText("No bouquets selected!")
            return

        target_dir = TMP_SELECTED
        if not os.path.exists(target_dir):
            try:
                os.makedirs(target_dir)
            except PermissionError:
                self["status"].setText("Permission denied: Unable to create directory.")
                return

        copied_files = []
        for bouquet_name in self.selected_bouquets:
            bouquet_file = next((f for l, f in self.bouquet_names.items() if bouquet_name in l), None)
            if not bouquet_file:
                continue
            source_path = os.path.join(TMP_DOWNLOAD, bouquet_file)
            destination_path = os.path.join(target_dir, bouquet_file)

            if os.path.exists(source_path):
                try:
                    shutil.copy(source_path, destination_path)
                    copied_files.append(bouquet_file)
                except Exception as e:
                    self["status"].setText(f"Error copying {bouquet_file}: {str(e)}")
                    return

        bouquets_tv_path = os.path.join('/etc/enigma2', 'bouquets.tv')
        if os.path.exists(bouquets_tv_path):
            with open(bouquets_tv_path, 'r') as f:
                lines = f.readlines()

            updated = False
            for bouquet_file in copied_files:
                if not any(bouquet_file in line for line in lines):
                    tmp_bouquets_tv = os.path.join(TMP_DOWNLOAD, 'bouquets.tv')
                    if os.path.exists(tmp_bouquets_tv):
                        with open(tmp_bouquets_tv, 'r') as f:
                            for line in f:
                                if bouquet_file in line:
                                    lines.append(line)
                                    updated = True
                                    break

            if updated:
                with open(bouquets_tv_path, 'w') as f:
                    f.writelines(lines)

        self["status"].setText("Files copied and bouquets.tv updated successfully!")

    def install(self):
        if not self.selected_bouquets:
            self.session.open(MessageBox, "No bouquets selected!", MessageBox.TYPE_ERROR)
            return

        self.session.openWithCallback(
            self.install_confirmed,
            MessageBox,
            "Install selected bouquets and common files?",
            MessageBox.TYPE_YESNO
        )

    def install_confirmed(self, result):
        if not result:
            return

        enigma2_dir = "/etc/enigma2"
        installed_files = []

        common_files = {
            'lamedb': enigma2_dir
        }

        for bouquet_name in self.selected_bouquets:
            bouquet_file = next((f for l, f in self.bouquet_names.items() if bouquet_name in l), None)
            if not bouquet_file:
                continue
            source_path = os.path.join(TMP_SELECTED, bouquet_file)
            destination_path = os.path.join(enigma2_dir, bouquet_file)

            if os.path.exists(source_path):
                try:
                    if os.path.exists(destination_path):
                        os.remove(destination_path)
                    shutil.copy(source_path, destination_path)
                    installed_files.append(bouquet_file)
                except Exception as e:
                    self.session.open(MessageBox, f"Failed to install {bouquet_file}: {str(e)}", MessageBox.TYPE_ERROR)
                    return

        for file_name, target_dir in common_files.items():
            source_path = os.path.join(TMP_DOWNLOAD, file_name)
            destination_path = os.path.join(target_dir, file_name)

            if os.path.exists(source_path):
                try:
                    if not os.path.exists(target_dir):
                        os.makedirs(target_dir)
                    if os.path.exists(destination_path):
                        os.remove(destination_path)
                    shutil.copy(source_path, destination_path)
                    installed_files.append(file_name)
                except Exception as e:
                    self.session.open(MessageBox, f"Failed to copy common file {file_name}: {str(e)}", MessageBox.TYPE_ERROR)
                    return

        if installed_files:
            self.reload_settings()
            self["status"].setText("Installation successful! Common files and bouquets are now active.")
        else:
            self["status"].setText("No files installed.")

    def reload_settings(self):
        try:
            eDVBDB.getInstance().reloadServicelist()
            eDVBDB.getInstance().reloadBouquets()
            self.session.open(
                MessageBox,
                "Reload successful! New bouquets and common files are now active. .::ciefpsettings::.",
                MessageBox.TYPE_INFO,
                timeout=5
            )
        except Exception as e:
            self.session.open(
                MessageBox,
                "Reload failed: " + str(e),
                MessageBox.TYPE_ERROR,
                timeout=5
            )

    def up(self):
        self["left_list"].up()

    def down(self):
        self["left_list"].down()

    def exit(self):
        self.close()

def main(session, **kwargs):
    session.open(CiefpChannelManager)

def Plugins(**kwargs):
    return [
        PluginDescriptor(
            name="{0} v{1}".format(PLUGIN_NAME, PLUGIN_VERSION),
            description="Bouquets update Plugin",
            icon=PLUGIN_ICON,
            where=PluginDescriptor.WHERE_PLUGINMENU,
            fnc=main
        )
    ]