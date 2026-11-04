import CloudUploadRounded from "@mui/icons-material/CloudUploadRounded";
import SearchRounded from "@mui/icons-material/SearchRounded";
import {
  Alert, Box, Button, Card, Chip, Dialog, DialogContent, DialogTitle, FormControl, Grid, InputLabel,
  MenuItem, Select, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import { useState } from "react";
import { api, useApi } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { ErrorState, fmtDate, Loading, PageHeader, Section, titleCase } from "../../components/common";

interface Doc {
  id: string; document_key: string; version: number; title: string; doc_type: string; authority: string; author: string;
  approval_status: string; approved_by: string | null; effective_date: string | null; expiry_date: string | null;
  procedure_type: string; patient_population: string; is_active: boolean; chunk_count: number;
}
const TYPES = ["DISCHARGE_INSTRUCTIONS", "RECOVERY_PROTOCOL", "EDUCATION", "MEDICATION_INSTRUCTIONS", "FAQ", "PROCEDURE_PROTOCOL"];
const AUTH = ["SURGEON_APPROVED", "HOSPITAL_APPROVED", "PROGRAM_APPROVED"];

export default function DocumentsPage() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useApi<Doc[]>("/documents");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [view, setView] = useState<string | null>(null);
  const [q, setQ] = useState("When can I drive?");
  const [proc, setProc] = useState("TKA");
  const [search, setSearch] = useState<{ meta: Record<string, unknown>; results: { title: string; section: string; score: number; content: string; authority: string; version: number }[] } | null>(null);
  const [form, setForm] = useState({ document_key: "", title: "", doc_type: "FAQ", authority: "PROGRAM_APPROVED", author: "", procedure_type: "ALL" });
  const [file, setFile] = useState<File | null>(null);
  const canManage = user!.permissions.includes("content:manage");
  const canApprove = user!.permissions.includes("content:approve");
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? ""} />;

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); setMsg({ ok: true, text: ok }); reload(); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };
  async function upload() {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    Object.entries(form).forEach(([k, v]) => fd.append(k, v));
    await run(() => api("/documents/upload", { form: fd }), `Uploaded ${form.title}. It is PENDING and not retrievable until approved.`);
  }

  return (
    <Stack gap={2.5}>
      <PageHeader title="Approved knowledge content" subtitle="The assistant can only answer from ACTIVE + APPROVED documents within their effective dates." />
      {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      <Card>
        <TableContainer>
          <Table size="small">
            <TableHead><TableRow>
              <TableCell>Document</TableCell><TableCell>Type</TableCell><TableCell>Authority</TableCell><TableCell>Procedure</TableCell>
              <TableCell>Status</TableCell><TableCell>Effective</TableCell><TableCell>Chunks</TableCell><TableCell />
            </TableRow></TableHead>
            <TableBody>
              {data.map((d) => {
                const expired = d.expiry_date && new Date(d.expiry_date) < new Date();
                return (
                  <TableRow key={d.id}>
                    <TableCell><Typography variant="body2" fontWeight={600}>{d.title}</Typography>
                      <Typography variant="caption" color="text.secondary">{d.document_key} · v{d.version} · {d.author}</Typography></TableCell>
                    <TableCell>{titleCase(d.doc_type)}</TableCell>
                    <TableCell><Chip size="small" variant="outlined" label={titleCase(d.authority)} /></TableCell>
                    <TableCell>{d.procedure_type}</TableCell>
                    <TableCell>
                      <Chip size="small" label={expired ? "EXPIRED" : d.approval_status}
                        color={expired ? "default" : d.approval_status === "APPROVED" ? "success" : d.approval_status === "PENDING" ? "warning" : "default"} />
                      {d.is_active && !expired && <Chip size="small" sx={{ ml: 0.5 }} color="primary" label="Retrievable" />}
                      {d.approved_by && <Typography variant="caption" display="block" color="text.secondary">by {d.approved_by}</Typography>}
                    </TableCell>
                    <TableCell><Typography variant="caption">{fmtDate(d.effective_date)}{d.expiry_date ? ` → ${fmtDate(d.expiry_date)}` : ""}</Typography></TableCell>
                    <TableCell>{d.chunk_count}</TableCell>
                    <TableCell>
                      <Stack direction="row" gap={0.5}>
                        <Button size="small" onClick={() => setView(d.id)}>View</Button>
                        {canApprove && d.approval_status === "PENDING" && <Button size="small" variant="contained" onClick={() => run(() => api(`/documents/${d.id}/approve`, { method: "POST" }), `${d.title} approved and active.`)}>Approve</Button>}
                        {canManage && d.is_active && <Button size="small" color="error" onClick={() => run(() => api(`/documents/${d.id}/retire`, { method: "POST" }), `${d.title} retired.`)}>Retire</Button>}
                      </Stack>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </Card>

      <Grid container spacing={2.5}>
        <Grid item xs={12} md={6}>
          <Section title="Test retrieval" icon={<SearchRounded color="primary" />} id="search">
            <Stack direction="row" gap={1} mb={2}>
              <TextField size="small" fullWidth value={q} onChange={(e) => setQ(e.target.value)} label="Patient question" />
              <TextField size="small" value={proc} onChange={(e) => setProc(e.target.value)} label="Procedure" sx={{ width: 120 }} />
              <Button variant="contained" onClick={async () => setSearch(await api("/documents/search", { body: { query: q, procedure_type: proc } }))}>Search</Button>
            </Stack>
            {search && (
              <Stack gap={1}>
                <Typography variant="caption" color="text.secondary">Terms: {String((search.meta.query_terms as string[]).join(", "))} · candidates {String(search.meta.candidates_considered)} · min score {String(search.meta.min_score)}</Typography>
                {search.results.length === 0 && <Alert severity="warning">No approved content matches — the assistant would refuse and create a care-team task.</Alert>}
                {search.results.map((r, i) => (
                  <Box key={i} p={1.5} sx={{ bgcolor: "#f9fafb", borderRadius: 2 }}>
                    <Typography variant="body2" fontWeight={600}>{r.title} › {r.section} <Chip size="small" label={`score ${r.score}`} /></Typography>
                    <Typography variant="body2" color="text.secondary">{r.content.slice(0, 220)}…</Typography>
                  </Box>
                ))}
              </Stack>
            )}
          </Section>
        </Grid>
        {canManage && (
          <Grid item xs={12} md={6}>
            <Section title="Upload a document" icon={<CloudUploadRounded color="primary" />} id="upload">
              <Stack gap={1.5}>
                <Stack direction="row" gap={1}>
                  <TextField size="small" fullWidth label="Document key (e.g. tka-faq)" value={form.document_key} onChange={(e) => setForm({ ...form, document_key: e.target.value })} />
                  <TextField size="small" label="Procedure" value={form.procedure_type} onChange={(e) => setForm({ ...form, procedure_type: e.target.value })} sx={{ width: 130 }} />
                </Stack>
                <TextField size="small" label="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
                <TextField size="small" label="Author" value={form.author} onChange={(e) => setForm({ ...form, author: e.target.value })} />
                <Stack direction="row" gap={1}>
                  <FormControl size="small" fullWidth><InputLabel>Type</InputLabel>
                    <Select label="Type" value={form.doc_type} onChange={(e) => setForm({ ...form, doc_type: e.target.value })}>{TYPES.map((t) => <MenuItem key={t} value={t}>{titleCase(t)}</MenuItem>)}</Select></FormControl>
                  <FormControl size="small" fullWidth><InputLabel>Authority</InputLabel>
                    <Select label="Authority" value={form.authority} onChange={(e) => setForm({ ...form, authority: e.target.value })}>{AUTH.map((t) => <MenuItem key={t} value={t}>{titleCase(t)}</MenuItem>)}</Select></FormControl>
                </Stack>
                <Button variant="outlined" component="label">{file ? file.name : "Choose .md, .txt or .pdf"}
                  <input hidden type="file" accept=".md,.txt,.pdf,.markdown" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Button>
                <Button variant="contained" disabled={!file || !form.document_key || !form.title || !form.author} onClick={upload}>Upload (pending approval)</Button>
              </Stack>
            </Section>
          </Grid>
        )}
      </Grid>
      <DocViewer id={view} onClose={() => setView(null)} />
    </Stack>
  );
}

function DocViewer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { data } = useApi<{ title: string; content: string; chunks: { index: number; section: string; tokens: number; embedding_model: string }[] }>(id ? `/documents/${id}` : null, [id]);
  return (
    <Dialog open={!!id} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{data?.title}</DialogTitle>
      <DialogContent>
        {data && (
          <Stack gap={2}>
            <Typography variant="body2" className="prewrap" sx={{ bgcolor: "#f9fafb", p: 2, borderRadius: 2 }}>{data.content}</Typography>
            <Typography variant="subtitle2">Chunks ({data.chunks.length})</Typography>
            {data.chunks.map((c) => <Typography key={c.index} variant="caption">#{c.index} · {c.section} · {c.tokens} tokens · {c.embedding_model}</Typography>)}
          </Stack>
        )}
      </DialogContent>
    </Dialog>
  );
}
