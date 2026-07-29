import { ipcMain } from 'electron';
import type { AetherOpportunityService } from '../services/aetherOpportunity/AetherOpportunityService';
export const AETHER_OPPORTUNITY_CHANNELS = {
  snapshot: 'aether:opportunity:snapshot', scout: 'aether:opportunity:scout', score: 'aether:opportunity:score',
  decide: 'aether:opportunity:decide', mandate: 'aether:opportunity:mandate', convert: 'aether:opportunity:convert',
} as const;
export function registerAetherOpportunityBridge(service: AetherOpportunityService): () => void {
  ipcMain.handle(AETHER_OPPORTUNITY_CHANNELS.snapshot, () => service.snapshot());
  ipcMain.handle(AETHER_OPPORTUNITY_CHANNELS.scout, (_event, input) => service.scout(input));
  ipcMain.handle(AETHER_OPPORTUNITY_CHANNELS.score, (_event, input) => service.score(input));
  ipcMain.handle(AETHER_OPPORTUNITY_CHANNELS.decide, (_event, candidateId, input) => service.decide(candidateId, input));
  ipcMain.handle(AETHER_OPPORTUNITY_CHANNELS.mandate, (_event, candidateId, input) => service.mandate(candidateId, input));
  ipcMain.handle(AETHER_OPPORTUNITY_CHANNELS.convert, (_event, candidateId) => service.convert(candidateId));
  return () => Object.values(AETHER_OPPORTUNITY_CHANNELS).forEach((channel) => ipcMain.removeHandler(channel));
}
