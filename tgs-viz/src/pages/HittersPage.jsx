import React from 'react';
import PlayerTable from '../components/PlayerTable';
import PlayerDetail from '../components/PlayerDetail';
import { HITTER_COLUMN_GROUPS } from '../lib/columns';
import { usePlayersWithFV, usePlayersWithDraftFV, usePlayersWithG5FV, usePlayersWithHybridFV, useHittersWithMarketValue } from '../hooks/usePlayerData';
import { formatMoney } from '../lib/marketValue';
import { useSelectedById } from '../hooks/useSelectedById';

export default function HittersPage({ players, isDraft = false, isFA = false, isIAFA = false, isR5 = false, allPlayers, marketRate }) {
  const playersWithFV = usePlayersWithFV(players);

  // Compute Draft FV for all players when allPlayers is available
  const playersWithDraftFV = usePlayersWithDraftFV(
    allPlayers ? playersWithFV : [],
    allPlayers || [],
    'hitter'
  );

  // Compute G5 FV (devPercentile-based peak WAA)
  const afterDraft = playersWithDraftFV.length > 0 ? playersWithDraftFV : playersWithFV;
  const playersWithG5 = usePlayersWithG5FV(afterDraft, allPlayers || players, 'hitter');

  // Compute Hybrid FV (combines FV + G5 + Draft FV)
  const playersWithHybrid = usePlayersWithHybridFV(playersWithG5);

  // Compute market value (fitted FA line, offer range, surplus)
  const finalPlayers = useHittersWithMarketValue(playersWithHybrid, marketRate);
  // The open card is kept by player ID and found again in the current rows, so
  // a data refresh or a park-basis switch shows the new numbers in the card.
  const { selected: selectedPlayer, select, clear } = useSelectedById({ hitter: finalPlayers });
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
    ? ['info', 'value', 'draftValue', 'runsSplit']
    : ['info', 'value', 'runsSplit', 'offense'];

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 pb-2">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white">
              {isDraft ? 'Draft Hitters' : isIAFA ? 'International Amateur Hitters' : isR5 ? 'Rule 5 Hitters' : isFA ? 'Free Agent Hitters' : 'Hitters'}
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              {players.length} players | Toggle column groups to explore data | Click a player for details
            </p>
          </div>
          {fit && fit.slope > 0 && (
            <div className="text-right">
              <p className="text-xs text-slate-500">FA market fit {(lowConfidence || banked) && '⚠️'}</p>
              <p className={`text-sm font-semibold ${lowConfidence ? 'text-orange-400' : banked ? 'text-amber-400' : 'text-green-400'}`}>
                {formatMoney(fit.slope)}/WAR + {formatMoney(fit.floor)}
              </p>
              <p className="text-[10px] text-slate-500">n={fit.n} FA signings, r²={fit.r2.toFixed(2)}</p>
              {lowConfidence && <p className="text-[10px] text-orange-400">Low data — few FA signings in sample</p>}
              {banked && (
                <p className="text-[10px] text-amber-400">
                  BANKED {banked.bankedAt} — live sample only n={banked.liveN}
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0">
        <PlayerTable
          players={finalPlayers}
          columnGroups={HITTER_COLUMN_GROUPS}
          defaultActiveGroups={defaultGroups}
          onPlayerClick={(row) => select(row, 'hitter')}
          selectedPlayerId={selectedPlayer?.ID}
          maxRows={1000}
          positionViewMode
          storageKey={isIAFA ? 'iafa-hitters' : isR5 ? 'r5-hitters' : isFA ? 'fa-hitters' : isDraft ? 'draft-hitters' : 'hitters'}
        />
      </div>

      {selectedPlayer && (
        <PlayerDetail
          player={selectedPlayer}
          onClose={clear}
          type="hitter"
        />
      )}
    </div>
  );
}
