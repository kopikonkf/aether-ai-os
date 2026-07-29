import { ipcMain } from 'electron';
import type { AetherExperimentService } from '../services/aetherExperiment/AetherExperimentService';
export const AETHER_EXPERIMENT_CHANNELS = {
  snapshot: 'aether:experiment:snapshot', configureSource: 'aether:experiment:configure-source', conform: 'aether:experiment:conform',
  refreshEvidence: 'aether:experiment:refresh-evidence', discover: 'aether:experiment:discover', createPlan: 'aether:experiment:create-plan',
  runPlan: 'aether:experiment:run-plan', recordDemand: 'aether:experiment:record-demand',
} as const;
export function registerAetherExperimentBridge(service: AetherExperimentService): () => void {
  ipcMain.handle(AETHER_EXPERIMENT_CHANNELS.snapshot, () => service.snapshot());
  ipcMain.handle(AETHER_EXPERIMENT_CHANNELS.configureSource, (_event, input) => service.configureSource(input));
  ipcMain.handle(AETHER_EXPERIMENT_CHANNELS.conform, (_event, adapterId, input) => service.conform(adapterId, input));
  ipcMain.handle(AETHER_EXPERIMENT_CHANNELS.refreshEvidence, (_event, input) => service.refreshEvidence(input));
  ipcMain.handle(AETHER_EXPERIMENT_CHANNELS.discover, (_event, input) => service.discover(input));
  ipcMain.handle(AETHER_EXPERIMENT_CHANNELS.createPlan, (_event, input) => service.createPlan(input));
  ipcMain.handle(AETHER_EXPERIMENT_CHANNELS.runPlan, (_event, planId) => service.runPlan(planId));
  ipcMain.handle(AETHER_EXPERIMENT_CHANNELS.recordDemand, (_event, runId, input) => service.recordDemand(runId, input));
  return () => Object.values(AETHER_EXPERIMENT_CHANNELS).forEach((channel) => ipcMain.removeHandler(channel));
}
