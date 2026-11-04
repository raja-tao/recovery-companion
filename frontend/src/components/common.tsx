import CheckCircleRounded from "@mui/icons-material/CheckCircleRounded";
import ErrorRounded from "@mui/icons-material/ErrorRounded";
import InfoRounded from "@mui/icons-material/InfoRounded";
import ScheduleRounded from "@mui/icons-material/ScheduleRounded";
import WarningRounded from "@mui/icons-material/WarningRounded";
import {
  Alert as MuiAlert, Box, Card, CardContent, Chip, CircularProgress, Stack, Typography, type ChipProps,
} from "@mui/material";
import type { ReactNode } from "react";
import type { Severity } from "../api/types";
import { severityColors } from "../theme";

const SEV_ICON = { RED: ErrorRounded, AMBER: WarningRounded, GREEN: CheckCircleRounded, INFO: InfoRounded };
const SEV_LABEL = { RED: "Red — urgent", AMBER: "Amber — follow up", GREEN: "Green — on track", INFO: "Info" };
const SEV_SHORT = { RED: "RED", AMBER: "AMBER", GREEN: "GREEN", INFO: "INFO" };

/** Severity indicator: color + icon + text, never color alone. */
export function SeverityChip({ level, long = false, size = "small" }: { level?: Severity | null; long?: boolean; size?: ChipProps["size"] }) {
  const lv = (level ?? "GREEN") as Severity;
  const Icon = SEV_ICON[lv];
  const c = severityColors[lv];
  return (
    <Chip
      size={size}
      icon={<Icon style={{ color: c.main }} aria-hidden />}
      label={long ? SEV_LABEL[lv] : SEV_SHORT[lv]}
      aria-label={`Severity ${SEV_LABEL[lv]}`}
      sx={{ bgcolor: c.bg, color: c.main, border: `1px solid ${c.border}` }}
    />
  );
}

export function SlaChip({ sla }: { sla: { state: string; minutes_remaining: number | null } }) {
  const map: Record<string, { label: string; color: ChipProps["color"] }> = {
    ON_TRACK: { label: "On track", color: "default" },
    DUE_SOON: { label: "Due soon", color: "warning" },
    BREACHED: { label: "SLA breached", color: "error" },
    MET: { label: "SLA met", color: "success" },
  };
  const m = map[sla.state] ?? map.ON_TRACK;
  const mins = sla.minutes_remaining;
  const remaining =
    mins == null ? "" : mins >= 0 ? ` · ${fmtMinutes(mins)} left` : ` · ${fmtMinutes(-mins)} over`;
  return <Chip size="small" variant="outlined" color={m.color} icon={<ScheduleRounded />} label={m.label + (sla.state === "MET" ? "" : remaining)} />;
}

export function fmtMinutes(m: number) {
  if (m < 60) return `${Math.round(m)} min`;
  if (m < 1440) return `${Math.round(m / 60)} h`;
  return `${Math.round(m / 1440)} d`;
}

export function timeAgo(iso?: string | null) {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 60000;
  if (diff < 1) return "just now";
  if (diff < 60) return `${Math.round(diff)} min ago`;
  if (diff < 1440) return `${Math.round(diff / 60)} h ago`;
  if (diff < 2880) return "yesterday";
  return `${Math.round(diff / 1440)} days ago`;
}

export const fmtDateTime = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
export const fmtDate = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }) : "—";
export const titleCase = (s: string) => s.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <Stack alignItems="center" py={6} gap={2} role="status" aria-live="polite">
      <CircularProgress size={28} />
      <Typography color="text.secondary">{label}</Typography>
    </Stack>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <MuiAlert severity="error" action={onRetry ? <Chip label="Retry" onClick={onRetry} clickable /> : undefined}>
      {message}
    </MuiAlert>
  );
}

export function Section({ title, icon, action, children, id }: { title: string; icon?: ReactNode; action?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <Card component="section" aria-labelledby={id ? `${id}-title` : undefined}>
      <CardContent>
        <Stack direction="row" alignItems="center" justifyContent="space-between" mb={1.5} gap={1}>
          <Stack direction="row" alignItems="center" gap={1}>
            {icon}
            <Typography variant="h6" component="h2" id={id ? `${id}-title` : undefined}>
              {title}
            </Typography>
          </Stack>
          {action}
        </Stack>
        {children}
      </CardContent>
    </Card>
  );
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "flex-end" }} mb={3} gap={1}>
      <Box>
        <Typography variant="h4" component="h1">{title}</Typography>
        {subtitle && <Typography color="text.secondary" mt={0.5}>{subtitle}</Typography>}
      </Box>
      {action}
    </Stack>
  );
}

export function EmptyState({ text }: { text: string }) {
  return <Typography color="text.secondary" py={2}>{text}</Typography>;
}
