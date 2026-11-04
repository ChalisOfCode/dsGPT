import type { AttachmentRecord } from "./Attachments";
import type { components } from "./api-schema";
export type SendMessage = components["schemas"]["MessageCreate"];
export interface Conversation {
  id: string;
  title: string;
  hidden: number;
  pinned: number;
  pin_order: number;
  revision: number;
  model_id: string | null;
}
export interface Message {
  id: string;
  conversation_id: string;
  role: string;
  content: string;
  status: string;
  ordinal: number;
  run_id?: string | null;
  run_error_code?: string | null;
  research?: number;
  attachments?: AttachmentRecord[];
}
export interface Model {
  id: string;
  label: string;
  context: number;
  output_tokens: number;
}
export interface Run {
  id: string;
  message_id: string;
  status: string;
  error_code: string | null;
}
export interface Snapshot {
  run: Run;
  message: Message;
  cursor: number;
}
export const terminal = (status: string) =>
  ["completed", "failed", "interrupted", "cancelled"].includes(status);
