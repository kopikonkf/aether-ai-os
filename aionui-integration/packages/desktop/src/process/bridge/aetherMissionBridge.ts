import { ipcMain } from 'electron';
import type { AetherMissionService } from '../services/aetherMission/AetherMissionService';

const CHANNELS = {
  snapshot: 'aether:mission:snapshot',
  approve: 'aether:mission:approve',
  reject: 'aether:mission:reject',
  run: 'aether:mission:run',
  pause: 'aether:mission:pause',
  cancel: 'aether:mission:cancel',
} as const;

export function registerAetherMissionBridge(service: AetherMissionService): () => void {
  ipcMain.handle(CHANNELS.snapshot, () => service.snapshot());
  ipcMain.handle(CHANNELS.approve, (_event, missionId: string, reason: string) => service.approve(missionId, reason));
  ipcMain.handle(CHANNELS.reject, (_event, missionId: string, reason: string) => service.reject(missionId, reason));
  ipcMain.handle(CHANNELS.run, (_event, missionId: string, maximumSteps?: number) => service.run(missionId, maximumSteps));
  ipcMain.handle(CHANNELS.pause, (_event, missionId: string, reason: string) => service.pause(missionId, reason));
  ipcMain.handle(CHANNELS.cancel, (_event, missionId: string, reason: string) => service.cancel(missionId, reason));
  return () => Object.values(CHANNELS).forEach((channel) => ipcMain.removeHandler(channel));
}

export { CHANNELS as AETHER_MISSION_CHANNELS };
