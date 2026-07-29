import { ipcMain } from 'electron';
import type { AetherApprovalFilter } from '../../common/aetherApprovalTypes';
import type { AetherApprovalService } from '../services/aetherApproval/AetherApprovalService';

const CHANNELS = {
  snapshot: 'aether:approval:snapshot',
  get: 'aether:approval:get',
  approve: 'aether:approval:approve',
  reject: 'aether:approval:reject',
} as const;

export function registerAetherApprovalBridge(service: AetherApprovalService): () => void {
  ipcMain.handle(CHANNELS.snapshot, (_event, status?: AetherApprovalFilter) =>
    service.snapshot(status),
  );
  ipcMain.handle(CHANNELS.get, (_event, approvalId: string) =>
    service.get(approvalId),
  );
  ipcMain.handle(
    CHANNELS.approve,
    (_event, approvalId: string, reason: string, expectedActionHash: string) =>
      service.approve(approvalId, reason, expectedActionHash),
  );
  ipcMain.handle(
    CHANNELS.reject,
    (_event, approvalId: string, reason: string, expectedActionHash: string) =>
      service.reject(approvalId, reason, expectedActionHash),
  );

  return () => Object.values(CHANNELS).forEach((channel) => ipcMain.removeHandler(channel));
}

export { CHANNELS as AETHER_APPROVAL_CHANNELS };
