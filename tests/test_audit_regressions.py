"""Generic A-E audit regressions: public boundaries, not product policies."""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from codex_dispatcher.allowlist import (
    AllowlistError, normalize_allowlist, require_nonempty_allowlist,
    require_repository_allowed,
)
from codex_dispatcher.github import GitHubIssueSource, Issue, extract_ticket
from codex_dispatcher.ledger import CallableDuplicateChecker
from codex_dispatcher.safety import (
    ACTION_PROHIBITED, CONFIG_INVALID, PATH_DENIED, PATH_ESCAPE, PATH_UNEXPECTED,
    ActionRule, MappingTicketSafetySurface, PathRule, RuleBasedSafetyPolicy,
    SafetyRuleConfig, SafetyViolation,
)
from codex_dispatcher.worker import assess, cli
from codex_dispatcher.worker.policies import CallableTicketValidator
from codex_dispatcher.validation import ValidationError


NUL = chr(0)  # Actual runtime NUL, never the six-character JSON escape spelling.
BAD_COLLECTIONS = (None, False, 1, 'secrets', b'secrets', bytearray(b'x'),
                   {}, {'safe': 'force_push'}, [None], [False], [1],
                   [['secrets/x']], [{'path': 'secrets/x'}])


def policy() -> RuleBasedSafetyPolicy:
    return RuleBasedSafetyPolicy(SafetyRuleConfig(
        (PathRule('deny.secret', '^secrets(/|$)'),),
        (PathRule('protect.base', '^foundation(/|$)'),),
        (ActionRule('prohibit.force', 'force_push'),),
    ))


def assess_ticket(ticket=None, **overrides):
    args = dict(validate_ticket=CallableTicketValidator(lambda t: None),
                safety_policy=policy(), ticket_safety_surface=MappingTicketSafetySurface(),
                duplicate_check=CallableDuplicateChecker(lambda t: False),
                repository_allowlist=frozenset({'acme/demo'}), repository='acme/demo')
    args.update(overrides)
    return assess(Issue(1, 'fixture', '{}', 'local'), {} if ticket is None else ticket, **args)


class PathAndSurfaceRegressions(unittest.TestCase):
    def test_actual_nul_assessment(self):
        for path in (NUL, NUL+'src/x', 'src/'+NUL+'x', 'src/x'+NUL):
            with self.subTest(path=path):
                self.assertEqual(assess_ticket({'paths': [path]})['disposition'], 'blocked')

    def test_actual_nul_direct_ticket_policy(self):
        with self.assertRaises(ValidationError):
            policy().require_safe_ticket(paths=['src/'+NUL+'x'], texts=[])

    def test_actual_nul_each_diff_side(self):
        for declared, changed in (([NUL], []), ([], [NUL]), ([NUL], [NUL])):
            with self.subTest(declared=declared, changed=changed):
                with self.assertRaises(ValidationError):
                    policy().validate_candidate_diff(declared_paths=declared, changed_paths=changed, patch_text='')

    def test_invalid_path_cannot_be_hidden_by_noop_policy(self):
        noop = SimpleNamespace(require_safe_ticket=lambda **kw: None)
        self.assertEqual(assess_ticket({'paths': [NUL]}, safety_policy=noop)['disposition'], 'blocked')

    def test_supplied_surface_collections_reject_malformed_shapes(self):
        for field in ('paths', 'texts'):
            for value in BAD_COLLECTIONS:
                with self.subTest(field=field, value=value):
                    self.assertEqual(assess_ticket({field: value})['disposition'], 'blocked')

    def test_custom_surface_outputs_validated_before_policy(self):
        for field in ('paths', 'texts'):
            for value in BAD_COLLECTIONS:
                with self.subTest(field=field, value=value):
                    surface = SimpleNamespace(paths=lambda t: (), texts=lambda t: ())
                    setattr(surface, field, lambda t, v=value: v)
                    self.assertEqual(assess_ticket(ticket_safety_surface=surface,
                        safety_policy=SimpleNamespace(require_safe_ticket=lambda **kw: None))['disposition'], 'blocked')

    def test_direct_ticket_collections(self):
        for field in ('paths', 'texts'):
            for value in BAD_COLLECTIONS:
                with self.subTest(field=field, value=value):
                    args = dict(paths=[], texts=[])
                    args[field] = value
                    with self.assertRaises(ValidationError):
                        policy().require_safe_ticket(**args)

    def test_direct_diff_collections(self):
        for field in ('declared_paths', 'changed_paths'):
            for value in BAD_COLLECTIONS:
                with self.subTest(field=field, value=value):
                    args = dict(declared_paths=[], changed_paths=[], patch_text='')
                    args[field] = value
                    with self.assertRaises(ValidationError):
                        policy().validate_candidate_diff(**args)

    def test_invalid_patch_rejected_even_without_action_rules(self):
        p = RuleBasedSafetyPolicy(SafetyRuleConfig((), (), ()))
        for text in (None, False, 1, [], {}, b''):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                p.validate_candidate_diff(declared_paths=[], changed_paths=[], patch_text=text)

    def test_empty_and_missing_fields_remain_valid(self):
        for ticket in ({}, {'paths': [], 'texts': []}, {'paths': (), 'texts': ()}):
            with self.subTest(ticket=ticket):
                self.assertEqual(assess_ticket(ticket)['disposition'], 'eligible')

    def test_rules_still_reject_well_formed_surfaces(self):
        for paths, texts, code in ((['./secrets//x/'], [], PATH_DENIED),
                                    ([], ['force_push'], ACTION_PROHIBITED),
                                    (['../out'], [], PATH_ESCAPE)):
            with self.subTest(code=code), self.assertRaises(SafetyViolation) as ctx:
                policy().require_safe_ticket(paths=paths, texts=texts)
            self.assertIn(code, ctx.exception.codes)

    def test_posix_lexical_vocabulary_unchanged(self):
        for path in ('', '.', './', 'src//ok/', '..\\out', 'C:\\out',
                     'src/\nfile', 'src/\tfile', 'src/caf\u00e9', 'src/cafe\u0301', 'secrets\u2215x'):
            with self.subTest(path=path):
                policy().validate_candidate_diff(declared_paths=[path], changed_paths=[path], patch_text='')

    def test_unicode_names_remain_distinct(self):
        with self.assertRaises(SafetyViolation) as ctx:
            policy().validate_candidate_diff(declared_paths=['src/caf\u00e9'], changed_paths=['src/cafe\u0301'], patch_text='')
        self.assertEqual(ctx.exception.codes, (PATH_UNEXPECTED,))


class CollaboratorRegressions(unittest.TestCase):
    def test_duplicate_requires_boolean_direct_and_wrapped(self):
        for value in (None, 0, 1, '', 'false', [], {}, {'duplicate': False}):
            for wrapped in (False, True):
                with self.subTest(value=value, wrapped=wrapped):
                    fn = lambda t, v=value: v
                    checker = CallableDuplicateChecker(fn) if wrapped else SimpleNamespace(is_duplicate=fn)
                    self.assertEqual(assess_ticket(duplicate_check=checker)['disposition'], 'blocked')

    def test_duplicate_adapter_rejects_unknown_independently(self):
        with self.assertRaises(ValidationError):
            CallableDuplicateChecker(lambda t: None).is_duplicate({})

    def test_boolean_decisions_preserved(self):
        for value, expected in ((False, 'eligible'), (True, 'blocked')):
            with self.subTest(value=value):
                self.assertEqual(assess_ticket(duplicate_check=CallableDuplicateChecker(lambda t: value))['disposition'], expected)

    def test_validator_and_safety_must_return_none(self):
        for value in (False, True, 0, [], {}, {'allowed': False}, SafetyViolation.from_codes(['DENIED'])):
            for kind in ('validator', 'wrapped_validator', 'safety'):
                with self.subTest(value=value, kind=kind):
                    if kind == 'safety':
                        kw = dict(safety_policy=SimpleNamespace(require_safe_ticket=lambda **kw: value))
                    else:
                        fn = lambda t: value
                        kw = dict(validate_ticket=CallableTicketValidator(fn) if kind == 'wrapped_validator' else SimpleNamespace(validate=fn))
                    self.assertEqual(assess_ticket(**kw)['disposition'], 'blocked')

    def test_validator_adapter_rejects_false_independently(self):
        with self.assertRaises(ValidationError):
            CallableTicketValidator(lambda t: False).validate({})

    def test_expected_collaborator_errors_block(self):
        for error in (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError):
            def fail(*args, **kw):
                raise error('fixture failure')
            for kw in (dict(validate_ticket=SimpleNamespace(validate=fail)),
                       dict(safety_policy=SimpleNamespace(require_safe_ticket=fail)),
                       dict(ticket_safety_surface=SimpleNamespace(paths=fail, texts=lambda t: [])),
                       dict(duplicate_check=SimpleNamespace(is_duplicate=fail))):
                with self.subTest(error=error, seam=next(iter(kw))):
                    self.assertEqual(assess_ticket(**kw)['disposition'], 'blocked')

    def test_missing_methods_and_wrong_ticket_shapes_block(self):
        for seam in ('validate_ticket', 'safety_policy', 'ticket_safety_surface', 'duplicate_check'):
            with self.subTest(seam=seam):
                self.assertEqual(assess_ticket(**{seam: object()})['disposition'], 'blocked')
        for ticket in (False, 1, [], 'x'):
            with self.subTest(ticket=ticket):
                self.assertEqual(assess_ticket(ticket)['disposition'], 'blocked')

    def test_process_control_exceptions_not_swallowed(self):
        for error in (KeyboardInterrupt, SystemExit):
            def fail(t):
                raise error()
            with self.subTest(error=error), self.assertRaises(error):
                assess_ticket(validate_ticket=SimpleNamespace(validate=fail))

    def test_direct_assess_refuses_false_environment_before_collaborators(self):
        validate = mock.Mock()
        for value in ('false', '0', '', ' true ', 'garbage'):
            with self.subTest(value=value), mock.patch.dict(os.environ, {'CODEX_DISPATCHER_DRY_RUN': value}):
                with self.assertRaises(RuntimeError):
                    assess_ticket(validate_ticket=SimpleNamespace(validate=validate))
        validate.assert_not_called()

    def test_direct_assess_preserves_truthy_values(self):
        for value in ('true', 'TRUE', '1', 'yes', 'on'):
            with self.subTest(value=value), mock.patch.dict(os.environ, {'CODEX_DISPATCHER_DRY_RUN': value}):
                self.assertEqual(assess_ticket()['disposition'], 'eligible')


class AllowlistRegressions(unittest.TestCase):
    def test_invalid_containers_and_entries_rejected_consistently(self):
        for value in ('acme/demo-other', b'acme/demo', {'acme/demo': False},
                      ['acme/demo'], 1, frozenset(), {''}, {' '}, {None}, {1}, {'acme/'+NUL}, {'acme/de\tmo'}):
            with self.subTest(value=value):
                with self.assertRaises(AllowlistError):
                    require_nonempty_allowlist(value)
                self.assertEqual(assess_ticket(repository_allowlist=value)['disposition'], 'blocked')

    def test_membership_exact_and_sets_valid(self):
        for repositories in ({'acme/demo'}, frozenset({'acme/demo'})):
            for repo, expected in (('acme/demo', 'eligible'), ('acme/dem', 'blocked'),
                                   ('acme/demo/', 'blocked'), ('Acme/demo', 'blocked')):
                with self.subTest(repositories=repositories, repo=repo):
                    self.assertEqual(assess_ticket(repository=repo, repository_allowlist=repositories)['disposition'], expected)

    def test_blank_target_rejected_by_helper(self):
        for repo in ('', ' ', NUL):
            with self.subTest(repo=repo), self.assertRaises(AllowlistError):
                require_repository_allowed(repo, {repo})

    def test_normalization_is_explicit_not_coercive(self):
        self.assertEqual(normalize_allowlist(iter([' acme/demo ', '', 'acme/demo'])), frozenset({'acme/demo'}))
        for value in ('acme/demo', {'acme/demo': 1}, [None], [1], None):
            with self.subTest(value=value), self.assertRaises(AllowlistError):
                normalize_allowlist(value)

    def test_source_rejects_route_delimiters_without_http(self):
        with mock.patch('urllib.request.urlopen') as urlopen:
            for repo in ('acme/demo?x', 'acme/demo#x', 'acme/%2e%2e', 'acme/..', './demo',
                         'acme/de\\mo', 'acme/'+NUL, 'acme/de\nmo'):
                with self.subTest(repo=repo), self.assertRaises(ValueError):
                    GitHubIssueSource(repo, None, allowed_repositories=frozenset({repo}))
            urlopen.assert_not_called()

    def test_source_preserves_safe_dotted_hyphenated_names(self):
        src = GitHubIssueSource('acme-team/demo.repo_1', None, allowed_repositories={'acme-team/demo.repo_1'})
        self.assertEqual(src.repository, 'acme-team/demo.repo_1')

    def test_source_constructs_expected_get_route(self):
        payload = json.dumps(dict(number=7, title='fixture', body='{}', html_url='local')).encode()
        with mock.patch('urllib.request.urlopen', return_value=io.BytesIO(payload)) as get:
            src = GitHubIssueSource('acme/demo', None, allowed_repositories={'acme/demo'})
            self.assertEqual(src.get_issue(7).number, 7)
        request = get.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.github.com/repos/acme/demo/issues/7')
        self.assertEqual(request.get_method(), 'GET')


class ExtractionRegressions(unittest.TestCase):
    def test_duplicate_keys_at_every_depth_raw_and_fenced(self):
        bodies = ('{"paths":["secrets/x"],"paths":[]}', '{"outer":{"x":1,"x":2}}',
                  '{"outer":[{"x":1,"x":2}]}', '{"x":1,"\\u0078":2}')
        for body in bodies:
            for text in (body, '```json\n'+body+'\n```'):
                with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'duplicate JSON'):
                    extract_ticket(text)

    def test_non_json_constants_at_every_depth_raw_and_fenced(self):
        for constant in ('NaN', 'Infinity', '-Infinity'):
            for body in ('{"n":'+constant+'}', '{"outer":[{"n":'+constant+'}]}'):
                for text in (body, '```json\n'+body+'\n```'):
                    with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'non-JSON'):
                        extract_ticket(text)

    def test_valid_opaque_json_unchanged(self):
        body = '{"a":[null,true,false,1,-2,3.5],"b":{"x":"NaN"},"c":{"x":"Infinity"}}'
        self.assertEqual(extract_ticket(body), json.loads(body))


class ConfigRegressions(unittest.TestCase):
    def test_invalid_string_regex_flags_are_controlled(self):
        for flags in (re.LOCALE, 1 << 1000):
            with self.subTest(flags=flags), self.assertRaises(SafetyViolation) as ctx:
                RuleBasedSafetyPolicy(SafetyRuleConfig((PathRule('id', 'x', flags),), (), ()))
            self.assertEqual(ctx.exception.codes, (CONFIG_INVALID,))

    def test_regexflag_and_family_local_ids_remain_valid(self):
        p = RuleBasedSafetyPolicy(SafetyRuleConfig(
            (PathRule('shared', '^secret', re.IGNORECASE),),
            (PathRule('shared', '^foundation'),), (),
        ))
        with self.assertRaises(SafetyViolation) as ctx:
            p.require_safe_ticket(paths=['SECRET'], texts=[])
        self.assertEqual(ctx.exception.codes, (PATH_DENIED,))

    def test_duplicate_ids_rejected_with_config_invalid(self):
        configs = (SafetyRuleConfig((), (), (ActionRule('same', 'one'), ActionRule('same', 'two'))),
                   SafetyRuleConfig((PathRule('same', 'one'), PathRule('same', 'two')), (), ()))
        for config in configs:
            with self.subTest(config=config), self.assertRaises(SafetyViolation) as ctx:
                RuleBasedSafetyPolicy(config)
            self.assertEqual(ctx.exception.codes, (CONFIG_INVALID,))

    def test_rule_family_shape_types_and_fields_validated(self):
        configs = (None, SafetyRuleConfig([], (), ()), SafetyRuleConfig(None, (), ()),
                   SafetyRuleConfig((None,), (), ()), SafetyRuleConfig((PathRule(' ', 'x'),), (), ()),
                   SafetyRuleConfig((PathRule('id', b'x'),), (), ()),
                   SafetyRuleConfig((PathRule('id', 'x', True),), (), ()))
        for config in configs:
            with self.subTest(config=config), self.assertRaises(SafetyViolation) as ctx:
                RuleBasedSafetyPolicy(config)
            self.assertEqual(ctx.exception.codes, (CONFIG_INVALID,))

    def test_unique_actions_collect_all_matches(self):
        p = RuleBasedSafetyPolicy(SafetyRuleConfig((), (), (ActionRule('one', 'one'), ActionRule('two', 'two'))))
        with self.assertRaises(SafetyViolation) as ctx:
            p.require_safe_ticket(paths=[], texts=['one two'])
        self.assertEqual({d.subject for d in ctx.exception.details}, {'one', 'two'})


class CliRegressions(unittest.TestCase):
    def run_cli(self, path, *extra):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(['--ticket-file', str(path), '--allowlist', 'acme/demo',
                             '--repository', 'acme/demo', '--demo-pass-policies', *extra])
        return code, json.loads(output.getvalue())

    def test_nul_and_malformed_surfaces_in_json_files_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'ticket.json'
            for payload in ({'paths': [NUL]}, {'paths': None}, {'texts': 'force_push'}, {'paths': [1]}):
                with self.subTest(payload=payload):
                    path.write_text(json.dumps(payload), encoding='utf-8')
                    code, result = self.run_cli(path)
                    self.assertEqual(code, 2)
                    self.assertEqual(result['disposition'], 'blocked')

    def test_duplicate_key_and_constant_files_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'ticket.json'
            for body in ('{"x":1,"x":2}', '```json\n{"n":-Infinity}\n```'):
                with self.subTest(body=body):
                    path.write_text(body, encoding='utf-8')
                    code, result = self.run_cli(path)
                    self.assertEqual(code, 2)
                    self.assertEqual(result['disposition'], 'blocked')

    def test_file_and_decode_errors_produce_structured_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            invalid = Path(tmp)/'invalid.json'
            invalid.write_bytes(b'\xff')
            for path in (invalid, Path(tmp)/'missing', Path(tmp), Path(tmp)/NUL):
                with self.subTest(path=path):
                    code, result = self.run_cli(path)
                    self.assertEqual(code, 2)
                    self.assertEqual(result['disposition'], 'refused')
                    self.assertEqual(result['issues_processed'], 0)
                    self.assertFalse(result['agent_invoked'])

    def test_cli_does_not_silently_normalize_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'ticket.json'
            path.write_text('{}', encoding='utf-8')
            code, result = self.run_cli(path, '--allowlist', ' acme/other ', '--repository', 'acme/other')
            self.assertEqual(code, 2)
            self.assertEqual(result['disposition'], 'blocked')
