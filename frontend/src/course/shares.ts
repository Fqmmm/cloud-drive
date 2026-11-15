export interface ShareCreated {
  id: string;
  shareToken: string;
  shareUrl: string;
  extractCode: string | null;
  expireTime: string | null;
}
export interface ShareEntry {
  id: string;
  fileId: string;
  fileName: string;
  shareToken: string;
  shareUrl: string;
  accessType: number;
  expireTime: string | null;
  createTime: string;
  status: "ACTIVE" | "CANCELLED" | "EXPIRED";
}
export interface ShareDetails {
  requiresCode: boolean;
  fileName: string | null;
  fileSize: number | null;
  expireTime: string | null;
}
export function expiry(value: string | null) {
  return value ? new Date(value).toLocaleString() : "永久有效";
}
