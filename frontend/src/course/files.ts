export interface FileItem {
  id: string;
  originalName: string;
  fileSize: number;
  mimeType: string;
  createTime: string;
  isDirectory: boolean;
  parentId: string;
}
export interface Listing {
  breadcrumb: { id: string; name: string }[];
  items: FileItem[];
}
export interface Quota {
  totalBytes: number;
  usedBytes: number;
}
export function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1048576) return `${(value / 1024).toFixed(1)} KiB`;
  if (value < 1073741824) return `${(value / 1048576).toFixed(1)} MiB`;
  return `${(value / 1073741824).toFixed(1)} GiB`;
}
