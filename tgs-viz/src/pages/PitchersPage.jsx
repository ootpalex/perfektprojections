import React from 'react';
import PlayerTable from '../components/PlayerTable';
import PlayerDetail from '../components/PlayerDetail';
import { PITCHER_COLUMN_GROUPS } from '../lib/columns';
import { usePlayersWithFV, usePlayersWithDraftFV, usePlayersWithG5FV, usePlayersWithHybridFV, usePitchersWithMarketValue } from '../hooks/usePlayerData';
import { formatMoney } from '../lib/marketValue';
import { useSelectedById } from '../hooks/useSelectedById';

export default function PitchersPage({ players, isDraft = false, isFA = false, isIAFA = false, isR5 = false, allPlayers, marketRate }) {
  const playersWithFV = usePlayersWithFV(players);

  // Compute Draft FV for all players when allPlayers is available
  const playersWithDraftFV = usePlayersWithDraftFV(
    allPlayers ? playersWithFV : [],
    allPlayers || [],
    'pitcher'
  );

  // Compute G5 FV (devPercentile-based peak WAA)
  const afterDraft = playersWithDraftFV.length > 0 ? playersWithDraftFV : playersWithFV;
  const playersWithG5 = usePlayersWithG5FV(afterDraft, allPlayers || players, 'pitcher');

  // Compute Hybrid FV (combines FV + G5 + Draft FV)
  const playersWithHybrid = usePlayersWithHybridFV(playersWithG5);

  // Compute market value (fitted FA line, offer range, surplus)
  const finalPlayers = usePitchersWithMarketValue(playersWithHybrid, marketRate);
  // The open card is kept by player ID and found again in the current rows, so
  // a data refresh or a park-basis switch shows the new numbers in the card.
  const { selected: selectedPlayer, select, clear } = useSelectedById({ pitcher: finalPlayers });
  const fit = marketRate?.pooled;
  const lowConfidence = marketRate?.lowConfidence;
  // A banked fit carries lowConfidence:false, so without this the stale line would show
  // in green AND suppress the warning the collapsed live sample would have raised —
  // silently stale dollars on the page free agents are actually shopped from.
  const banked = marketRate?.provenance?.used === 'banked' ? marketRate.provenance : null;

  const defaultGroups = isIAFA
    ? ['info', 'signing', 'value', 'draftValue']
    : isFA
    ? ['info', 'value', 'marketCurrent']
    : isDraft
    ? ['info', 'value', 'draftValue', 'ratingsVR']
    : ['info', 'value', 'valueRP', 'ratingsVR'];

  return (
    <div className="ns-page">
      <header className="ns-page-head">
        <div>
          <h1>
            {isDraft ? 'Draft Pitchers' : isIAFA ? 'International Amateur Pitchers' : isR5 ? 'Rule 5 Pitchers' : isFA ? 'Free Agent Pitchers' : 'Pitchers'}
          </h1>
          <p className="ns-page-sub">
            <b>{players.length}</b> players · Toggle column groups to explore data · Click a player for details
          </p>
        </div>
        {fit && fit.slope > 0 && (
          <div className="text-right">
            <p className={`ns-label ${lowConfidence || banked ? 'ns-warn' : 'ns-muted'}`}>FA market fit</p>
            <p className={`text-[13px] font-semibold ${lowConfidence || banked ? 'ns-warn' : 'ns-good'}`}>
              {formatMoney(fit.slope)}/WAR + {formatMoney(fit.floor)}
            </p>
            <p className="text-[11px] ns-muted">n={fit.n} FA signings, r²={fit.r2.toFixed(2)}</p>
            {lowConfidence && <p className="text-[11px] ns-warn">Low data — few FA signings in sample</p>}
            {banked && (
              <p className="text-[11px] ns-warn">
                BANKED {banked.bankedAt} — live sample only n={banked.liveN}
              </p>
            )}
          </div>
        )}
      </header>

      <div className="flex-1 min-h-0">
        <PlayerTable
          players={finalPlayers}
          columnGroups={PITCHER_COLUMN_GROUPS}
          defaultActiveGroups={defaultGroups}
          onPlayerClick={(row) => select(row, 'pitcher')}
          selectedPlayerId={selectedPlayer?.ID}
          maxRows={1000}
          title="Pitchers"
          storageKey={isIAFA ? 'iafa-pitchers' : isR5 ? 'r5-pitchers' : isFA ? 'fa-pitchers' : isDraft ? 'draft-pitchers' : 'pitchers'}
        />
      </div>

      {selectedPlayer && (
        <PlayerDetail
          player={selectedPlayer}
          onClose={clear}
          type="pitcher"
        />
      )}
    </div>
  );
}
