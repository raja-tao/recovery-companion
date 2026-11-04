import {
  Alert, Button, Card, Chip, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography,
} from "@mui/material";
import { useState } from "react";
import { api, useApi } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { ErrorState, fmtDateTime, Loading, PageHeader, SeverityChip, titleCase } from "../../components/common";

interface Protocol {
  id: string; rule_id: string; version: number; name: string; description: string; severity: "RED" | "AMBER"; category: string;
  condition: unknown; response_minutes: number; assigned_team: string; status: string; approved_at: string | null;
}

type Cond = { all?: Cond[]; any?: Cond[]; not?: Cond; fact?: string; op?: string; value?: unknown };
const show = (c: Cond): string => {
  if (c.all) return c.all.map(show).join(" AND ");
  if (c.any) return "(" + c.any.map(show).join(" OR ") + ")";
  if (c.not) return "NOT " + show(c.not);
  return `${c.fact} ${c.op}${c.value === null || c.value === undefined ? "" : " " + (Array.isArray(c.value) ? `[${c.value.join(", ")}]` : String(c.value))}`;
};

export default function Protocols() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useApi<Protocol[]>("/protocols");
  const [msg, setMsg] = useState<string | null>(null);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? ""} />;
  const canApprove = user!.permissions.includes("protocol:approve");
  return (
    <Stack gap={2}>
      <PageHeader title="Warning protocols" subtitle="Deterministic rules evaluated on every check-in. The AI never sets or changes these thresholds." />
      <Alert severity="info">Only the latest APPROVED version of each rule is active. Drafts have no effect until a surgeon approves them.</Alert>
      {msg && <Alert severity="success" onClose={() => setMsg(null)}>{msg}</Alert>}
      <Card>
        <TableContainer>
          <Table size="small">
            <TableHead><TableRow>
              <TableCell>Rule</TableCell><TableCell>Severity</TableCell><TableCell>Condition</TableCell><TableCell>Response</TableCell>
              <TableCell>Team</TableCell><TableCell>Status</TableCell><TableCell />
            </TableRow></TableHead>
            <TableBody>
              {data.map((p) => (
                <TableRow key={p.id} sx={{ opacity: p.status === "APPROVED" ? 1 : 0.75 }}>
                  <TableCell><Typography fontWeight={600} variant="body2">{p.name}</Typography><Typography variant="caption" color="text.secondary">{p.rule_id} v{p.version}</Typography></TableCell>
                  <TableCell><SeverityChip level={p.severity} /></TableCell>
                  <TableCell sx={{ fontFamily: "ui-monospace, monospace", fontSize: 12, maxWidth: 380 }}>{show(p.condition as Cond)}</TableCell>
                  <TableCell>{p.response_minutes} min</TableCell>
                  <TableCell>{titleCase(p.assigned_team)}</TableCell>
                  <TableCell><Chip size="small" label={p.status} color={p.status === "APPROVED" ? "success" : p.status === "DRAFT" ? "warning" : "default"} variant="outlined" />
                    {p.approved_at && <Typography variant="caption" display="block" color="text.secondary">{fmtDateTime(p.approved_at)}</Typography>}</TableCell>
                  <TableCell>{canApprove && p.status === "DRAFT" && (
                    <Button size="small" variant="contained" onClick={async () => { await api(`/protocols/${p.id}/approve`, { method: "POST" }); setMsg(`${p.rule_id} v${p.version} approved and active.`); reload(); }}>Approve</Button>
                  )}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Card>
    </Stack>
  );
}
