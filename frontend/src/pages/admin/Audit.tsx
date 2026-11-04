import LockRounded from "@mui/icons-material/LockRounded";
import {
  Alert, Box, Card, Chip, Collapse, IconButton, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  TextField, Typography,
} from "@mui/material";
import ExpandMoreRounded from "@mui/icons-material/ExpandMoreRounded";
import { Fragment, useState } from "react";
import { useApi } from "../../api/client";
import { ErrorState, fmtDateTime, Loading, PageHeader } from "../../components/common";

interface Ev { id: string; occurred_at: string; actor_email: string | null; actor_role: string | null; patient_id: string | null; action: string; resource_type: string | null; outcome: string; details: Record<string, unknown>; request_id: string | null; ip_address: string | null }

export default function AuditPage() {
  const [action, setAction] = useState("");
  const [applied, setApplied] = useState("");
  const { data, error, loading } = useApi<Ev[]>(`/audit?limit=300${applied ? `&action=${encodeURIComponent(applied)}` : ""}`, [applied]);
  const [open, setOpen] = useState<string | null>(null);

  return (
    <Stack gap={2}>
      <PageHeader title="Audit trail" subtitle="Every login, data access, check-in, AI response, alert and human action." />
      <Alert severity="info" icon={<LockRounded />}>Read-only. Records are append-only; the database rejects any update or delete.</Alert>
      <Stack direction="row" gap={1} flexWrap="wrap">
        <TextField size="small" label="Action prefix (e.g. AI_, ALERT_, CARE_TEAM_)" value={action} onChange={(e) => setAction(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setApplied(action)} sx={{ minWidth: 320 }} />
        {["", "AI_", "ALERT_", "CARE_TEAM_", "CHECKIN", "PHI_VIEW", "LOGIN", "ACCESS_DENIED", "CAREGIVER", "DOCUMENT"].map((a) => (
          <Chip key={a || "all"} label={a || "All"} clickable color={applied === a ? "primary" : "default"} onClick={() => { setAction(a); setApplied(a); }} />
        ))}
      </Stack>
      {loading && <Loading />}
      {error && <ErrorState message={error} />}
      {data && (
        <Card>
          <TableContainer>
            <Table size="small">
              <TableHead><TableRow><TableCell /><TableCell>Time</TableCell><TableCell>Actor</TableCell><TableCell>Action</TableCell><TableCell>Resource</TableCell><TableCell>Outcome</TableCell><TableCell>Patient</TableCell></TableRow></TableHead>
              <TableBody>
                {data.map((e) => (
                  <Fragment key={e.id}>
                    <TableRow hover>
                      <TableCell padding="checkbox"><IconButton size="small" aria-label="Details" onClick={() => setOpen(open === e.id ? null : e.id)}><ExpandMoreRounded /></IconButton></TableCell>
                      <TableCell>{fmtDateTime(e.occurred_at)}</TableCell>
                      <TableCell>{e.actor_email ?? "system"}<Typography variant="caption" display="block" color="text.secondary">{e.actor_role}</Typography></TableCell>
                      <TableCell><Typography variant="body2" fontWeight={600}>{e.action}</Typography></TableCell>
                      <TableCell>{e.resource_type}</TableCell>
                      <TableCell><Chip size="small" label={e.outcome} color={e.outcome === "SUCCESS" ? "default" : "error"} variant="outlined" /></TableCell>
                      <TableCell><Typography variant="caption">{e.patient_id?.slice(0, 8) ?? "—"}</Typography></TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell colSpan={7} sx={{ p: 0, border: open === e.id ? undefined : 0 }}>
                        <Collapse in={open === e.id} unmountOnExit>
                          <Box component="pre" sx={{ m: 0, p: 2, bgcolor: "#f9fafb", fontSize: 12, overflowX: "auto", whiteSpace: "pre-wrap" }}>
                            {JSON.stringify({ ...e.details, request_id: e.request_id, ip: e.ip_address }, null, 2)}
                          </Box>
                        </Collapse>
                      </TableCell>
                    </TableRow>
                  </Fragment>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      )}
    </Stack>
  );
}
