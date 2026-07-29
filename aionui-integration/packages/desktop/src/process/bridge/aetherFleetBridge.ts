import { ipcMain } from 'electron';
import type { FleetJobKind } from '../../common/aetherFleetTypes';
import type { AetherFleetService } from '../services/aetherFleet/AetherFleetService';

const CHANNELS = {
  snapshot: 'aether:fleet:snapshot',
  runDue: 'aether:fleet:run-due',
  runJob: 'aether:fleet:run-job',
  updateJob: 'aether:fleet:update-job',
  acknowledge: 'aether:fleet:acknowledge-incident',
  resolve: 'aether:fleet:resolve-incident',
} as const;

export function registerAetherFleetBridge(service: AetherFleetService): () => void {
  ipcMain.handle(CHANNELS.snapshot, () => service.snapshot());
  ipcMain.handle(CHANNELS.runDue, () => service.runDue());
  ipcMain.handle(CHANNELS.runJob, (_event, kind: FleetJobKind) => service.runJob(kind));
  ipcMain.handle(CHANNELS.updateJob, (_event, kind: FleetJobKind, input) => service.updateJob(kind, input));
  ipcMain.handle(CHANNELS.acknowledge, (_event, incidentId: string, reason: string) =>
    service.acknowledgeIncident(incidentId, reason),
  );
  ipcMain.handle(CHANNELS.resolve, (_event, incidentId: string, reason: string) =>
    service.resolveIncident(incidentId, reason),
  );

  return () => Object.values(CHANNELS).forEach((channel) => ipcMain.removeHandler(channel));
}

export { CHANNELS as AETHER_FLEET_CHANNELS };
