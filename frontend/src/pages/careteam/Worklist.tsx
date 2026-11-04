import DirectionsCarRounded from "@mui/icons-material/DirectionsCarRounded";
import EventRounded from "@mui/icons-material/EventRounded";
import ReportProblemRounded from "@mui/icons-material/ReportProblemRounded";
import {
  Box, Button, Card, CardActionArea, CardContent, Chip, Grid, Stack, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApi } from "../../api/client";
import type { Alert } from "../../api/types";
import { EmptyState, ErrorState, fmtDateTime, Loading, PageHeader, Section, SeverityChip, SlaChip, timeAgo, titleCase } from "../../components/common";
import { severityColors } from "../../theme";

interface Worklist {
  counts: Record<string, number>;
  items: Alert[];
  upcoming_followups: { appointment_id: string; patient_id: string; patient_name: string; type: string; scheduled_at: string; provider: string; transportation_status: string }[];
  generated_at: string;
}

const FILTERS: Record<string, (a: Alert) => boolean> = {
  all: () => true,
  red: (a) => a.severity === "RED",
  amber: (a) => a.severity === "AMBER",
  missed: (a) => a.category === "MISSED_CHECKIN",
  meds: (a) => a.category.startsWith("MEDICATION"),
  tasks: (a) => a.severity === "INFO" || ["TRANSPORTATION", "UNANSWERED_QUESTION"].includes(a.category),
};

export default function Worklist() {
  const nav = useNavigate();
  const { data, error, loading, reload } = useApi<Worklist>("/care-team/worklist");
  const [filter, setFilter] = useState("all");
  useEffect(() => {
    const t = setInterval(reload, 30000); // live-ish refresh
    return () => clearInterval(t);
  }, [reload]);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? "Unavailable"} onRetry={reload} />;
  const c = data.counts;
  const tiles = [
    { key: "red", label: "RED — urgent", value: c.red, sev: "RED" as const },
    { key: "amber", label: "AMBER — follow up", value: c.amber, sev: "AMBER" as const },
    { key: "missed", label: "Missed check-ins", value: c.missed_checkins },
    { key: "meds", label: "Medication issues", value: c.medication_issues },
    { key: "tasks", label: "Care-team tasks", value: c.info + data.items.filter((a) => a.category === "TRANSPORTATION").length },
  ];
  const rows = data.items.filter(FILTERS[filter]);

  return (
    <Stack gap={2.5}>
      <PageHeader title="Patients needing attention"
        subtitle={<>Sorted by severity, then due time · updated {timeAgo(data.generated_at)} {c.sla_breached > 0 && <Chip size="small" color="error" label={`${c.sla_breached} SLA breached`} sx={{ ml: 1 }} />}</>}
        action={<Button onClick={reload} variant="outlined">Refresh</Button>} />

      <Grid container spacing={2}>
        {tiles.map((t) => (
          <Grid item xs={6} sm={4} md key={t.key}>
            <Card sx={{ borderColor: filter === t.key ? "primary.main" : undefined, borderWidth: filter === t.key ? 2 : 1,
              bgcolor: t.sev && t.value ? severityColors[t.sev].bg : undefined }}>
              <CardActionArea onClick={() => setFilter(filter === t.key ? "all" : t.key)} aria-pressed={filter === t.key}>
                <CardContent>
                  <Typography variant="body2" color="text.secondary" fontWeight={600}>{t.label}</Typography>
                  <Typography variant="h4" component="p" sx={{ color: t.sev && t.value ? severityColors[t.sev].main : undefined }}>{t.value}</Typography>
                </CardContent>
              </CardActionArea>
            </Card>
          </Grid>
        ))}
      </Grid>

      <Card>
        <Stack direction="row" justifyContent="space-between" alignItems="center" px={2} pt={2} flexWrap="wrap" gap={1}>
          <Stack direction="row" gap={1} alignItems="center"><ReportProblemRounded color="primary" /><Typography variant="h6" component="h2">Worklist</Typography></Stack>
          <ToggleButtonGroup size="small" exclusive value={filter} onChange={(_, v) => v && setFilter(v)} aria-label="Filter worklist">
            {Object.keys(FILTERS).map((k) => <ToggleButton key={k} value={k}>{k === "all" ? "All" : titleCase(k)}</ToggleButton>)}
          </ToggleButtonGroup>
        </Stack>
        <TableContainer sx={{ mt: 1 }}>
          <Table size="medium" aria-label="Patients needing attention">
            <TableHead>
              <TableRow>
                <TableCell>Patient</TableCell><TableCell>Risk</TableCell><TableCell>Reason</TableCell>
                <TableCell>Last check-in</TableCell><TableCell>Action</TableCell><TableCell>Status</TableCell><TableCell>SLA</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.length === 0 && <TableRow><TableCell colSpan={7}><EmptyState text="Nothing needs attention in this view." /></TableCell></TableRow>}
              {rows.map((a) => (
                <TableRow key={a.id} hover sx={{ cursor: "pointer", borderLeft: `4px solid ${severityColors[a.severity].main}` }}
                  onClick={() => nav(`/care-team/patients/${a.patient_id}?alert=${a.id}`)}
                  tabIndex={0} onKeyDown={(e) => e.key === "Enter" && nav(`/care-team/patients/${a.patient_id}?alert=${a.id}`)}>
                  <TableCell><Typography fontWeight={600}>{a.patient_name}</Typography><Typography variant="caption" color="text.secondary">{a.patient_mrn}</Typography></TableCell>
                  <TableCell><SeverityChip level={a.severity} /></TableCell>
                  <TableCell sx={{ maxWidth: 360 }}>
                    <Typography variant="body2" fontWeight={600}>{a.reason ?? a.trigger}</Typography>
                    <Typography variant="caption" color="text.secondary">{a.rule_id} · {titleCase(a.category)} · {timeAgo(a.created_at)}</Typography>
                  </TableCell>
                  <TableCell>{timeAgo(a.last_checkin_at)}</TableCell>
                  <TableCell><Chip size="small" label={a.action} variant="outlined" /></TableCell>
                  <TableCell><Chip size="small" label={titleCase(a.status)} /></TableCell>
                  <TableCell><SlaChip sla={a.sla} /><Typography variant="caption" display="block" color="text.secondary">{a.required_response_minutes} min target</Typography></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Card>

      <Section title="Upcoming follow-ups (next 3 days)" icon={<EventRounded color="primary" />} id="followups">
        {data.upcoming_followups.length === 0 ? <EmptyState text="None." /> : (
          <Stack gap={1}>
            {data.upcoming_followups.map((f) => (
              <Stack key={f.appointment_id} direction="row" justifyContent="space-between" alignItems="center" sx={{ cursor: "pointer" }}
                onClick={() => nav(`/care-team/patients/${f.patient_id}`)}>
                <Box>
                  <Typography fontWeight={600}>{f.patient_name}</Typography>
                  <Typography variant="body2" color="text.secondary">{titleCase(f.type)} · {fmtDateTime(f.scheduled_at)} · {f.provider}</Typography>
                </Box>
                <Chip size="small" icon={<DirectionsCarRounded />} label={titleCase(f.transportation_status)}
                  color={f.transportation_status === "NEEDS_HELP" ? "warning" : "default"} variant="outlined" />
              </Stack>
            ))}
          </Stack>
        )}
      </Section>
    </Stack>
  );
}
