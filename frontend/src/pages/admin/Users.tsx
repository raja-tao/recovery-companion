import {
  Alert, Button, Card, Chip, FormControl, Grid, InputLabel, MenuItem, Select, Stack, Switch, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import { useState } from "react";
import { api, useApi } from "../../api/client";
import { ErrorState, fmtDateTime, Loading, PageHeader, Section } from "../../components/common";

interface U { id: string; email: string; full_name: string; role: string; title: string | null; is_active: boolean; last_login_at: string | null }
interface P { id: string; name: string; description: string; procedure_types: string[]; duration_days: number; targets: Record<string, number> }

export default function UsersPage() {
  const users = useApi<U[]>("/admin/users");
  const programs = useApi<P[]>("/admin/programs");
  const [form, setForm] = useState({ email: "", full_name: "", role: "NURSE", password: "" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  if (users.loading && !users.data) return <Loading />;
  if (users.error || !users.data) return <ErrorState message={users.error ?? ""} />;

  async function create() {
    try {
      await api("/admin/users", { body: form });
      setMsg({ ok: true, text: `Created ${form.email}` });
      setForm({ email: "", full_name: "", role: "NURSE", password: "" });
      users.reload();
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }

  return (
    <Stack gap={2.5}>
      <PageHeader title="Users & programs" />
      {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      <Grid container spacing={2.5}>
        <Grid item xs={12} lg={8}>
          <Card>
            <TableContainer>
              <Table size="small">
                <TableHead><TableRow><TableCell>Name</TableCell><TableCell>Email</TableCell><TableCell>Role</TableCell><TableCell>Last login</TableCell><TableCell>Active</TableCell></TableRow></TableHead>
                <TableBody>
                  {users.data.map((u) => (
                    <TableRow key={u.id}>
                      <TableCell>{u.full_name}<Typography variant="caption" display="block" color="text.secondary">{u.title}</Typography></TableCell>
                      <TableCell>{u.email}</TableCell><TableCell><Chip size="small" label={u.role} /></TableCell>
                      <TableCell>{fmtDateTime(u.last_login_at)}</TableCell>
                      <TableCell><Switch checked={u.is_active} inputProps={{ "aria-label": `Active ${u.email}` }}
                        onChange={async (e) => {
                          try { await api(`/admin/users/${u.id}/active?active=${e.target.checked}`, { method: "POST" }); users.reload(); }
                          catch (err) { setMsg({ ok: false, text: (err as Error).message }); }
                        }} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Card>
        </Grid>
        <Grid item xs={12} lg={4}>
          <Stack gap={2.5}>
            <Section title="Add user" id="adduser">
              <Stack gap={1.5}>
                <TextField size="small" label="Full name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
                <TextField size="small" label="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                <FormControl size="small"><InputLabel>Role</InputLabel>
                  <Select label="Role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                    {["PATIENT", "CAREGIVER", "NURSE", "SURGEON", "ADMIN"].map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
                  </Select></FormControl>
                <TextField size="small" type="password" label="Initial password (10+ chars)" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
                <Button variant="contained" onClick={create} disabled={!form.email || !form.full_name || form.password.length < 10}>Create</Button>
              </Stack>
            </Section>
            <Section title="Programs" id="programs">
              {(programs.data ?? []).map((p) => (
                <Stack key={p.id} mb={1.5}>
                  <Typography fontWeight={600}>{p.name}</Typography>
                  <Typography variant="body2" color="text.secondary">{p.procedure_types.join(", ")} · {p.duration_days} days</Typography>
                  <Typography variant="caption" color="text.secondary">Targets: {Object.entries(p.targets).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")}</Typography>
                </Stack>
              ))}
            </Section>
          </Stack>
        </Grid>
      </Grid>
    </Stack>
  );
}
