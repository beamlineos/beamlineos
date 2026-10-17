// SPDX-License-Identifier: MIT






import Gdm from 'gi://Gdm';
import GLib from 'gi://GLib';
import System from 'system';

const service = 'gdm-password';
const user = 'dev';
const loop = new GLib.MainLoop(null, false);
let status = 1;

function finish(code, message) {
    print(message);
    status = code;
    loop.quit();
}

const verifier = new Gdm.Client().open_reauthentication_channel_sync(user, null);

verifier.connect('secret-info-query', (v, name) => v.call_answer_query(name, user, null, null));
verifier.connect('problem', (v, name, problem) => print(`gdm problem: ${problem}`));
verifier.connect('service-unavailable', (v, name, message) =>
    finish(1, `BEAMLINE_UNLOCK_FAILED service unavailable: ${message}`));
verifier.connect('verification-failed', () => finish(1, 'BEAMLINE_UNLOCK_FAILED verification failed'));
verifier.connect('verification-complete', () => finish(0, 'BEAMLINE_UNLOCK_OK'));
verifier.call_begin_verification_for_user(service, user, null, (v, result) => {
    try {
        v.call_begin_verification_for_user_finish(result);
    } catch (e) {
        finish(1, `BEAMLINE_UNLOCK_FAILED ${e.message}`);
    }
});
GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 90, () => {
    finish(1, 'BEAMLINE_UNLOCK_FAILED timeout');
    return GLib.SOURCE_REMOVE;
});
loop.run();
System.exit(status);
