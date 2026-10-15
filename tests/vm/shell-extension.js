// SPDX-License-Identifier: MIT
import GLib from 'gi://GLib';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

export default class TestExtension extends Extension {
    enable() {
        GLib.file_set_contents(`${GLib.get_home_dir()}/beamline-extension-ran`, 'ran');
    }

    disable() {
    }
}
