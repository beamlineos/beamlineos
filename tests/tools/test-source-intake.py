#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Regression checks for source-set migration and frozen first-time intake (D63)."""
import importlib.util
import copy
import pathlib
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('integrate', pathlib.Path(__file__).resolve().parents[2] / 'tools/integrate.py')
integrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(integrate)


class SourceIntake(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.patch = patch.multiple(integrate, REPO=str(self.root), OUT=str(self.root / 'out'))
        self.patch.start()
        (self.root / 'project.refs').write_text('projects:\n  beamline: {}\n')
        self.comp = {'url': 'https://example.invalid/tools.git', 'branch': 'main',
                     'elements': ['posix/tools.bst'], 'refs': 'project.refs'}

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_lockfile_intake_preserves_local_slot_and_accepts_deliberate_changes(self):
        lock = self.root / 'Cargo.lock'
        element = self.root / 'elements/base/control.bst'
        element.parent.mkdir(parents=True)
        element.write_text('sources:\n- kind: local\n  path: files/control\n- kind: cargo\n  url: crates:crates\n')
        policy = {'lockfile': {'control': {'lockfile': 'Cargo.lock',
                  'element': 'base/control.bst', 'refs': 'project.refs'}}}
        text = ('version = 4\n[[package]]\nname = "control"\nversion = "0.1.0"\n'
                '[[package]]\nname = "serde"\nversion = "1.0.229"\n'
                'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
                'checksum = "' + 'a' * 64 + '"\n')
        lock.write_text(text)
        result = integrate.lockfile_sources(policy)
        entries = integrate.source_entries('project.refs', 'base/control.bst')
        self.assertEqual(entries[0], {})
        self.assertEqual(entries[1]['ref'][0]['sha'], 'a' * 64)
        self.assertEqual(result['control']['status'], 'FIXED')
        integrate.lockfile_sources(policy, check=True)
        before = (self.root / 'project.refs').read_bytes()
        lock.write_text(text.replace('a' * 64, 'b' * 64))
        with self.assertRaises(SystemExit):
            integrate.lockfile_sources(policy, check=True)
        self.assertEqual((self.root / 'project.refs').read_bytes(), before)
        integrate.lockfile_sources(policy)
        self.assertEqual(integrate.source_entries('project.refs', 'base/control.bst')[1]['ref'][0]['sha'], 'b' * 64)

    def test_lockfile_rejects_unverified_or_unapproved_sources(self):
        (self.root / 'Cargo.lock').write_text('[[package]]\nname="bad"\nversion="1"\nsource="git+https://example.invalid/x"\n')
        policy = {'lockfile': {'control': {'lockfile': 'Cargo.lock', 'element':'unused', 'refs':'project.refs'}}}
        with self.assertRaises(SystemExit):
            integrate.lockfile_sources(policy)

    def test_rename_preserves_crate_refs_and_removes_old_key(self):
        entries = [{'ref': 'a' * 40}, {'ref': [{'name': 'crate', 'sha': 'b' * 64}]}]
        integrate.write_source_entries('project.refs', {'old/tools.bst': entries})
        comp = dict(self.comp, renamed_from={'posix/tools.bst': 'old/tools.bst'})
        integrate.migrate_sources({'component': {'tools': comp}})
        self.assertEqual(integrate.source_entries('project.refs', 'posix/tools.bst'), entries)
        self.assertEqual(integrate.source_entries('project.refs', 'old/tools.bst'), [])

    def test_retry_restores_first_intake_without_upstream_lookup(self):
        entries = [{'ref': 'a' * 40}, {'ref': [{'name': 'crate', 'sha': 'b' * 64}]}]
        def resolve(*args):
            integrate.write_source_entries('project.refs', {'posix/tools.bst': entries})
            return {'selected_ref': 'a' * 40, 'commit': 'a' * 40, 'status': 'HEAD'}
        with patch.object(integrate, 'resolve_component', side_effect=resolve) as lookup:
            first = integrate.introduce_component('tools', self.comp, 'aarch64')
            integrate.write_source_entries('project.refs', {}, remove=('posix/tools.bst',))
            second = integrate.introduce_component('tools', self.comp, 'aarch64')
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(integrate.source_entries('project.refs', 'posix/tools.bst'), entries)

    def test_archive_retry_restores_commit_variable_without_upstream_lookup(self):
        comp = dict(self.comp, select='github-archive', commit_file='include/emacs.yml',
                    commit_variable='emacs-commit')
        path = self.root / comp['commit_file']
        path.parent.mkdir()
        path.write_text('variables:\n  emacs-commit: unresolved\n')
        def resolve(*args):
            integrate.write_variable(comp['commit_file'], comp['commit_variable'], 'a' * 40)
            integrate.write_ref('project.refs', 'posix/tools.bst', 'b' * 64)
            return {'selected_ref': 'a' * 40, 'commit': 'a' * 40,
                    'archive_sha256': 'b' * 64, 'status': 'HEAD'}
        with patch.object(integrate, 'resolve_component', side_effect=resolve) as lookup:
            first = integrate.introduce_component('tools', comp, 'aarch64')
            integrate.write_variable(comp['commit_file'], comp['commit_variable'], 'unresolved')
            integrate.write_source_entries('project.refs', {}, remove=('posix/tools.bst',))
            second = integrate.introduce_component('tools', comp, 'aarch64')
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(integrate.read_variable(comp['commit_file'], comp['commit_variable']), 'a' * 40)
        self.assertEqual(integrate.read_ref('project.refs', 'posix/tools.bst'), 'b' * 64)

    def test_frozen_ref_mismatch_is_rejected(self):
        integrate.write_ref('project.refs', 'posix/tools.bst', 'b' * 40)
        previous = {'snapshot': 'test', 'sources': {'tools': {'selected_ref': 'a' * 40}}}
        with self.assertRaises(SystemExit):
            integrate.frozen_sources({'component': {'tools': self.comp}}, previous, 'aarch64')

    def test_recipe_inherits_every_subproject_ref(self):
        sources = [{'kind': 'git_repo', 'url': 'gnome:shell.git', 'track': 'main', 'ref': 'a' * 40},
                   {'kind': 'git_repo', 'url': 'gnome:gvc.git', 'directory': 'subprojects/gvc',
                    'ref': {'commit': 'b' * 40, 'tags': ['v1']}}]
        original = {'sources': sources}
        ours = {'sources': [{k: v for k, v in s.items() if k != 'ref'} for s in sources] +
                           [{'kind': 'patch', 'path': 'files/patches/shell.patch'}]}
        entries = integrate.inherit_recipe(ours, original, 'shell')
        self.assertEqual(entries, [{'ref': 'a' * 40}, {'ref': sources[1]['ref']}, {}])
        entries[1]['ref']['tags'].append('mutated')
        self.assertEqual(original['sources'][1]['ref']['tags'], ['v1'])
        for key, value in [('url', 'gnome:other.git'), ('track', 'master')]:
            changed = copy.deepcopy(ours)
            changed['sources'][0][key] = value
            with self.assertRaises(SystemExit):
                integrate.inherit_recipe(changed, original, 'shell')

    def test_recipe_cannot_add_an_independently_selected_source(self):
        original = {'sources': [{'kind': 'git_repo', 'url': 'gnome:shell.git', 'ref': 'a' * 40}]}
        ours = {'sources': [{'kind': 'git_repo', 'url': 'gnome:shell.git'},
                           {'kind': 'git_repo', 'url': 'gnome:other.git', 'track': 'main'}]}
        with self.assertRaises(SystemExit):
            integrate.inherit_recipe(ours, original, 'shell')

    def test_frozen_recipe_rejects_changed_subproject_or_missing_refs(self):
        original = {'sources': [
            {'kind': 'git_repo', 'url': 'gnome:shell.git', 'ref': 'a' * 40},
            {'kind': 'git_repo', 'url': 'gnome:gvc.git', 'directory': 'subprojects/gvc',
             'ref': 'b' * 40}]}
        ours = {'sources': [{k: v for k, v in s.items() if k != 'ref'}
                            for s in original['sources']] +
                           [{'kind': 'patch', 'path': 'files/patches/shell.patch'}]}
        entry = {'component': 'gnome-build-meta', 'junction': 'junctions/gnome-build-meta.bst',
                 'upstream_element': 'core/shell.bst', 'element': 'overrides/shell.bst',
                 'refs': 'project.refs'}
        recipe = self.root / 'elements/overrides/shell.bst'
        recipe.parent.mkdir(parents=True)
        with recipe.open('w') as stream:
            integrate.yaml().dump(ours, stream)

        def checkout(argv, **kwargs):
            selected = pathlib.Path(argv[argv.index('--directory') + 1]) / 'elements/core/shell.bst'
            selected.parent.mkdir(parents=True)
            with selected.open('w') as stream:
                integrate.yaml().dump(original, stream)

        policy = {'recipe': {'shell': entry}}
        sources = {'gnome-build-meta': {'commit': 'c' * 40}}
        with patch.object(integrate.subprocess, 'run', side_effect=checkout):
            first = integrate.inherited_recipes(policy, sources, None, True, 'aarch64')
            previous = {'inherited_recipes': first}
            integrate.inherited_recipes(policy, sources, previous, True, 'aarch64')
            changed = copy.deepcopy(first['shell']['sources'])
            changed[1]['ref'] = 'd' * 40
            integrate.write_source_entries('project.refs', {'overrides/shell.bst': changed})
            with self.assertRaises(SystemExit):
                integrate.inherited_recipes(policy, sources, previous, True, 'aarch64')
            integrate.write_source_entries('project.refs', {}, remove=('overrides/shell.bst',))
            with self.assertRaises(SystemExit):
                integrate.inherited_recipes(policy, sources, previous, True, 'aarch64')


class OverrideMetadata(unittest.TestCase):
    def test_junction_overrides_are_read_without_comment_markers(self):
        with tempfile.TemporaryDirectory() as temporary:
            junction = pathlib.Path(temporary) / 'sdk.bst'
            junction.write_text('config:\n  overrides:\n    components/a.bst: junctions/gnome-build-meta.bst:sdk/a.bst\n'
                                '    components/own.bst: overrides/own.bst\n')
            upstream = 'config:\n  overrides:\n    components/a.bst: sdk/a.bst\n'
            with patch.object(integrate, 'FDSDK_JUNCTION', str(junction)), patch.object(integrate, 'run', return_value=upstream):
                self.assertEqual(integrate.gbm_override_drift({'mirror': '/unused', 'commit': 'a' * 40}), [])
                junction.write_text(junction.read_text().replace('sdk/a.bst', 'sdk/b.bst'))
                self.assertIn('components/a.bst', integrate.gbm_override_drift({'mirror': '/unused', 'commit': 'a' * 40})[0])

    def test_unregistered_override_fails_instead_of_silently_skipping_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            overrides = root / 'elements/overrides'
            overrides.mkdir(parents=True)
            (root / 'policy').mkdir()
            (root / 'policy/overrides.toml').write_text('[override]\n')
            (overrides / 'unknown.bst').write_text('kind: manual\n')
            with patch.multiple(integrate, REPO=str(root), OVERRIDES=str(overrides)), self.assertRaisesRegex(ValueError, 'provenance'):
                integrate.override_drift({})


if __name__ == '__main__':
    unittest.main()
