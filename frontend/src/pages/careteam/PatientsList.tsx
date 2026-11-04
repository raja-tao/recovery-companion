import SearchRounded from "@mui/icons-material/SearchRounded";
import {
  Card, Chip, InputAdornment, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField,
} from "@mui/material";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApi } from "../../api/client";
import type { PatientSummary } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ErrorState, fmtDate, Loading, PageHeader, SeverityChip } from "../../components/common";

export default function PatientsList() {
  const nav = useNavigate();
  const { user } = useAuth();
  const [q, setQ] = useState("");
  const { data, error, loading } = useApi<PatientSummary[]>("/patients");
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? ""} />;
  const rows = data.filter((p) => `${p.full_name} ${p.mrn} ${p.episode?.procedure_name}`.toLowerCase().includes(q.toLowerCase()));
  const clickable = user!.role !== "ADMIN";
  return (
    <Stack gap={2}>
      <PageHeader title="Enrolled patients" subtitle={`${data.length} synthetic patients in the 30-day program`} />
      <TextField placeholder="Search name, MRN or procedure" value={q} onChange={(e) => setQ(e.target.value)} sx={{ maxWidth: 420 }}
        InputProps={{ startAdornment: <InputAdornment position="start"><SearchRounded /></InputAdornment> }} inputProps={{ "aria-label": "Search patients" }} />
      <Card>
        <TableContainer>
          <Table>
            <TableHead><TableRow>
              <TableCell>Patient</TableCell><TableCell>MRN</TableCell><TableCell>Procedure</TableCell><TableCell>Surgery</TableCell>
              <TableCell>Day</TableCell><TableCell>Phase</TableCell><TableCell>Risk</TableCell>
            </TableRow></TableHead>
            <TableBody>
              {rows.map((p) => (
                <TableRow key={p.id} hover={clickable} sx={{ cursor: clickable ? "pointer" : undefined }}
                  onClick={() => clickable && nav(`/care-team/patients/${p.id}`)}>
                  <TableCell sx={{ fontWeight: 600 }}>{p.full_name}</TableCell>
                  <TableCell>{p.mrn}</TableCell>
                  <TableCell>{p.episode?.procedure_name}</TableCell>
                  <TableCell>{fmtDate(p.episode?.surgery_date)}</TableCell>
                  <TableCell>{p.episode?.recovery_day}</TableCell>
                  <TableCell><Chip size="small" variant="outlined" label={p.episode?.phase.label} /></TableCell>
                  <TableCell><SeverityChip level={p.current_risk} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Card>
    </Stack>
  );
}
