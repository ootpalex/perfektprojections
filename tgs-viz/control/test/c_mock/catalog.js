// Implementer C's test fixture: a catalog shaped like DESIGN 3.4, with the
// real task ids, flags and inputs from section 4. Used only by mockControl.js.

const SID_WHEN = { any: [{ no_token: 'TGS' }, { no_token: 'BLM' }] };
const CSRF_WHEN = {
  all: [
    { any: [{ no_token: 'TGS' }, { no_token: 'BLM' }] },
    { any: [{ all: [{ no_token: 'TGS' }, { no_token: 'BLM' }] }, { input_nonblank: 'sessionid' }] },
  ],
};

const F = (o = {}) => ({
  writes_app_data: false, heavy: false, long: false, endless: false, drives_ootp: false,
  needs_ootp_closed: false, needs_excel_closed: false, network: false, secret_inputs: false,
  hidden: false, read_only: false, needs_archive: false, ...o,
});

const secret = (name, label, ask_when, extra = {}) => ({
  name, type: 'secret', label, help: 'Leave blank when the token works.', required: false, default: null, ask_when, modes: ['console', 'job'], ...extra,
});

function task(id, title, group, o = {}) {
  const flags = F(o.flags);
  const steps = o.steps || [{ id: 's1', title, writes_app_data: !!flags.writes_app_data, data: !flags.read_only, app_leagues: [] }];
  return {
    id, title, group,
    description: o.description || `${title}.`,
    leagues: o.leagues || [],
    bat: o.bat || null,
    flags,
    locks: o.locks || (flags.read_only ? [] : [`task.${id}`]),
    time: o.time || 'Seconds',
    inputs: o.inputs || [],
    stop_modes: o.stop_modes || (flags.endless ? ['after_cycle', 'after_step', 'kill'] : ['after_step', 'kill']),
    steps: steps.map(s => ({ argv: ['python', 'tgs-viz\\tools\\selftest_steps.py', s.id], ...s })),
  };
}

const st = (ids, data = true, apps = []) => ids.map((id, i) => ({ id, title: id.replace(/_/g, ' '), writes_app_data: data, data, app_leagues: apps[i] || [] }));

export function buildCatalog({ selftest = true, settingsError = null, tokens = { TGS: true, BLM: true }, settingsLocal = false, myOrg = {} } = {}) {
  const tasks = [];
  if (!settingsError) {
    tasks.push(
      task('get_ratings', 'Get StatsPlus Ratings', 'everyday', {
        description: 'Pulls current ratings for TGS and BLM from StatsPlus, then rebuilds the draft boards, dev signals and ML scores.',
        bat: 'Get StatsPlus Ratings.bat', time: '5 to 15 minutes', leagues: ['TGS', 'BLM'],
        flags: { network: true, secret_inputs: true, writes_app_data: true, needs_archive: true },
        inputs: [secret('sessionid', 'Browser cookie: sessionid', SID_WHEN), secret('csrftoken', 'Browser cookie: csrftoken', CSRF_WHEN)],
      }),
      task('draft_board', 'Update Draft Board', 'everyday', { bat: 'Update Draft Board.bat', time: '1 to 2 minutes', flags: { network: true, writes_app_data: true } }),
      task('dispersal_board', 'Update Dispersal Board', 'everyday', {
        bat: 'Update Dispersal Board.bat', time: 'Under a minute', flags: { network: true, writes_app_data: true },
        inputs: [{ name: 'orgs', type: 'text', label: 'Orgs in the dispersal', help: 'Comma separated.', required: false, default: 'Atlanta Hammers,Detroit Tigers,San Francisco Giants,Seattle Mariners', ask_when: null, modes: ['job'] }],
      }),
      task('pull_report', 'Data date report', 'everyday', { description: 'Data date report: what the app is serving.', flags: { read_only: true } }),
      task('update.TGS', 'Update TGS', 'leagues', {
        time: '5 to 15 minutes', flags: { network: true, secret_inputs: true, writes_app_data: true, needs_archive: true },
        inputs: [secret('sessionid', 'Browser cookie: sessionid', { no_token: 'TGS' }), secret('csrftoken', 'Browser cookie: csrftoken', { no_token: 'TGS' })],
      }),
      task('update.RG', 'Update Regular Game', 'leagues', { bat: 'Update Regular Game.bat', time: 'About a minute', flags: { writes_app_data: true, needs_archive: true } }),
      task('get_history', 'Get StatsPlus History', 'season', {
        bat: 'Get StatsPlus History.bat', time: 'Minutes to about 2 hours (StatsPlus decides the waits)',
        flags: { network: true, secret_inputs: true, long: true, writes_app_data: true, needs_archive: true },
        inputs: [
          { name: 'league', type: 'choice', label: 'League', help: null, required: true, default: null, choices: [{ value: 'TGS', label: 'TGS' }, { value: 'BLM', label: 'BLM' }], ask_when: null, modes: ['console', 'job'] },
          secret('sessionid', 'Browser cookie: sessionid', { no_token_input: 'league' }),
          secret('csrftoken', 'Browser cookie: csrftoken', { no_token_input: 'league' }),
        ],
      }),
      task('grind_tgs', 'Grind TGS', 'calibration', {
        bat: 'Grind TGS.bat', time: 'Runs until you stop it; about 75 minutes per cycle', locks: ['ootp', 'clones.TGS', 'task.grind_tgs'],
        flags: { endless: true, drives_ootp: true, needs_excel_closed: true, heavy: true, writes_app_data: true, needs_archive: true },
        inputs: [
          { name: 'ootp_ready', type: 'confirm', label: 'OOTP 26 is open inside a league other than Baseline, and nothing else needs the mouse.', required: true, default: null, ask_when: null, modes: ['job'] },
          { name: 'runs', type: 'text', label: 'Clone runs per cycle', format: 'int', min: 1, max: 50, required: false, default: '10', ask_when: null, modes: ['console', 'job'] },
        ],
        steps: st(['winsim', 'calibrate'], true).map((s, i) => ({ ...s, data: i > 0 })),
      }),
      task('recalibrate_tgs', 'Recalibrate TGS', 'calibration', { bat: 'Recalibrate TGS.bat', locks: ['clones.TGS', 'task.recalibrate_tgs'], time: '1 to 3 minutes plus your answers', flags: { needs_excel_closed: true, writes_app_data: true, needs_archive: true } }),
      task('bank_dev', 'Bank Dev Seasons', 'dev', { bat: 'Bank Dev Seasons.bat', locks: ['dumps.DEV', 'task.bank_dev'], time: 'Hours (retrains the ML models; needs about 13 GB of memory)', flags: { heavy: true, long: true, writes_app_data: true, needs_archive: true } }),
      task('update.DEV', 'Update Dev test (all-AI sim)', 'dev', { locks: ['dumps.DEV', 'task.update.DEV'], time: 'About 20 seconds per new season', flags: { writes_app_data: true, needs_archive: true } }),
      task('ootp_check_26', 'Check OOTP (26)', 'ootp', { bat: 'ootp\\1 - Check OOTP (26).bat', locks: ['ootp', 'task.ootp_check_26'], steps: st(['list', 'grab'], false) }),
      task('doctor', 'Setup check', 'setup', { description: 'Checks Python, Node, the app packages, the settings, tokens, OOTP folders and league data.', flags: { read_only: true } }),
      task('token_check', 'Check StatsPlus tokens', 'setup', { flags: { read_only: true, network: true } }),
      task('token_set', 'Replace a StatsPlus token', 'setup', {
        steps: st(['token'], false),
        inputs: [
          { name: 'league', type: 'choice', label: 'League', required: true, default: null, choices: [{ value: 'TGS', label: 'TGS' }, { value: 'BLM', label: 'BLM' }], ask_when: null, modes: ['console', 'job'] },
          secret('token', 'Token', null, { required: true }),
        ],
      }),
      task('restore_ratings_db', 'Rebuild ratings archive', 'setup', { flags: { hidden: true } }),
      task('new_league', 'New league', 'leagues', { flags: { hidden: true, writes_app_data: true, needs_archive: true } }),
      task('new_league_cleanup', 'Clean up unfinished league', 'leagues', {
        flags: { hidden: true },
        inputs: [{ name: 'job_id', type: 'text', label: 'Job id', required: true, default: null, ask_when: null, modes: ['job'] }],
      }),
    );
    if (selftest) {
      const S = (id, title, o = {}) => task(id, title, 'selftest', { time: 'Seconds', ...o });
      tasks.push(
        S('selftest.ok', 'Self test ok', { steps: st(['print']) }),
        S('selftest.fail_collect', 'Self test fail collect', { steps: st(['s1', 's2', 's3']) }),
        S('selftest.fail_fast', 'Self test fail fast', { steps: st(['s1', 's2', 's3']) }),
        S('selftest.confirm', 'Self test confirm', { steps: st(['sync']) }),
        S('selftest.confirm_zero', 'Self test confirm zero', { steps: st(['sync']) }),
        S('selftest.gate', 'Self test gate', { steps: st(['before', 'gate', 'after']) }),
        S('selftest.long', 'Self test long', { time: 'Two minutes', steps: st(['sleep_1', 'sleep_2', 'sleep_3', 'sleep_4', 'sleep_5', 'sleep_6']) }),
        S('selftest.loop', 'Self test loop', { flags: { endless: true }, steps: st(['sleep_a', 'sleep_b']) }),
        S('selftest.secret', 'Self test secret', {
          flags: { secret_inputs: true }, steps: st(['echo_secret']),
          inputs: [secret('token', 'Test secret', null, { help: 'At least 8 characters.' })],
        }),
        S('selftest.touch', 'Self test touch', {
          flags: { writes_app_data: true }, steps: st(['touch'], true, [['TGS']]),
          inputs: [{ name: 'file', type: 'text', label: 'File under public/data', required: false, default: 'TGS/r5.json', ask_when: null, modes: ['console', 'job'] }],
        }),
        S('selftest.corrupt', 'Self test corrupt', { flags: { writes_app_data: true }, steps: st(['corrupt'], true, [['RG']]) }),
        S('selftest.stdin', 'Self test stdin', { steps: st(['stdin']) }),
        S('selftest.hands_off', 'Self test hands off', { steps: st(['click'], false).map(s => ({ ...s, drives_ootp: true })) }),
        S('selftest.archive', 'Self test archive', { flags: { needs_archive: true }, steps: st(['sleep0']) }),
        S('selftest.leagues', 'Self test leagues', { steps: st(['t1', 't2', 'b1', 'none'], true, [['TGS'], ['TGS'], ['BLM'], []]) }),
      );
    }
  } else {
    tasks.push(task('doctor', 'Setup check', 'setup', { flags: { read_only: true } }));
  }

  const groups = [
    ['everyday', 'Everyday'], ['leagues', 'Your leagues'], ['season', 'Season end'],
    ['calibration', 'Calibration and clone sims'], ['dev', 'DEV research league and ML'],
    ['ootp', 'OOTP tools'], ['setup', 'Setup and checks'],
  ];
  if (selftest && !settingsError) groups.push(['selftest', 'Self tests']);

  const leagues = settingsError ? [] : [
    { id: 'TGS', name: 'TGS', type: 'statsplus', enabled: true, pending: false, added_by_wizard: false, in_app: true, update_task: 'update.TGS', token_line: 'TGS=' },
    { id: 'BLM', name: 'BLM', type: 'statsplus', enabled: true, pending: false, added_by_wizard: false, in_app: true, update_task: 'update.BLM', token_line: 'BLM=' },
    { id: 'RG', name: 'Regular Game', type: 'local_export', enabled: true, pending: false, added_by_wizard: false, in_app: true, update_task: 'update.RG', token_line: null },
    { id: 'DEV', name: 'Dev test (all-AI sim)', type: 'dev', enabled: true, pending: false, added_by_wizard: false, in_app: true, update_task: 'update.DEV', token_line: null },
  ];

  return {
    schema: 1,
    generated: new Date().toISOString(),
    groups: groups.map(([id, title]) => ({ id, title })),
    tasks,
    leagues,
    state: {
      tokens,
      ootp_installs: { 26: { path: 'C:\\OOTP 26\\data\\saved_games', exists: true }, 27: { path: 'C:\\Users\\x\\Documents\\OOTP Baseball 27\\saved_games', exists: true } },
      ratings_db_exists: true,
      settings_local: settingsLocal,
      settings_error: settingsError,
      watch_files: [],
    },
    app_config: settingsError ? { leagues: {} } : {
      leagues: {
        TGS: { name: 'TGS', my_org: myOrg.TGS || 'Chicago Cubs' },
        BLM: { name: 'BLM', my_org: myOrg.BLM || 'Chicago (N) Cubs' },
        RG: { name: 'Regular Game', my_org: myOrg.RG || null },
        DEV: { name: 'Dev test (all-AI sim)', my_org: null },
      },
    },
  };
}
