import { Alert, Box, Button, Card, CardContent, Chip, Stack, Typography } from "@mui/material";
import { useState } from "react";
import { api, useApi } from "../../api/client";
import { EmptyState, ErrorState, fmtDateTime, Loading, PageHeader } from "../../components/common";

interface Pending {
  version_id: string; version: number; plan_title: string; patient_name: string; change_summary: string; created_by: string; created_at: string;
  content: { surgeon_instructions: string[]; warning_signs: { call_911: string[]; same_day: string[] }; daily_tasks: unknown[] };
}

export default function PlanApprovals() {
  const { data, error, loading, reload } = useApi<Pending[]>("/plans/pending");
  const [msg, setMsg] = useState<string | null>(null);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? ""} />;
  return (
    <Stack gap={2.5}>
      <PageHeader title="Recovery plans awaiting approval" subtitle="Only approved plans are shown to patients as clinical guidance." />
      {msg && <Alert severity="success" onClose={() => setMsg(null)}>{msg}</Alert>}
      {data.length === 0 && <EmptyState text="No plans waiting for approval." />}
      {data.map((p) => (
        <Card key={p.version_id}><CardContent>
          <Stack direction="row" justifyContent="space-between" flexWrap="wrap" gap={1}>
            <Box>
              <Typography variant="h6">{p.patient_name}</Typography>
              <Typography>{p.plan_title} · v{p.version}</Typography>
              <Typography variant="body2" color="text.secondary">Created by {p.created_by} · {fmtDateTime(p.created_at)} · {p.change_summary}</Typography>
            </Box>
            <Chip label="Pending approval" color="warning" variant="outlined" />
          </Stack>
          <Typography variant="subtitle2" mt={2}>Surgeon instructions</Typography>
          {p.content.surgeon_instructions.map((s) => <Typography key={s} variant="body2">• {s}</Typography>)}
          <Typography variant="subtitle2" mt={1.5}>Warning signs</Typography>
          <Typography variant="body2">911: {p.content.warning_signs.call_911.join(", ")}</Typography>
          <Typography variant="body2">Same day: {p.content.warning_signs.same_day.join(", ")}</Typography>
          <Typography variant="body2" color="text.secondary" mt={1}>{p.content.daily_tasks.length} daily task templates</Typography>
          <Button variant="contained" sx={{ mt: 2 }} onClick={async () => {
            try {
              await api(`/plans/versions/${p.version_id}/approve`, { method: "POST" });
              setMsg(`Approved plan for ${p.patient_name}. Daily tasks generated.`);
              reload();
            } catch (e) { setMsg((e as Error).message); }
          }}>Approve plan</Button>
        </CardContent></Card>
      ))}
    </Stack>
  );
}
