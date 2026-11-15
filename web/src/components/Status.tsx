import type { Status } from "../lib/api";
import { statusLabel } from "../lib/format";
import { Icon } from "./Icons";

const ICON = { verified: "check", review: "flag", not_disclosed: "none" } as const;
const CLS = { verified: "ok", review: "warn", not_disclosed: "none" } as const;

export function StatusBadge({ status, text }: { status: Status; text?: string }) {
  return (
    <span className={`status ${CLS[status]}`}>
      <Icon name={ICON[status]} />
      {text ?? statusLabel[status]}
    </span>
  );
}
