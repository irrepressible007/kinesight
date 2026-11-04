import type { StepStatus } from "./types";

export const STATUS_TEXT: Record<StepStatus, string> = {
  PASS: "Pass",
  FAIL_MISSING: "Step skipped",
  FAIL_COUNT_SHORTFALL: "Contact count short",
  FAIL_SHORT_DURATION: "Contact too short",
  FAIL_ORDER: "Out of order",
};
