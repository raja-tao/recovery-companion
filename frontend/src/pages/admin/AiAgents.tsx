import AccountTreeRounded from "@mui/icons-material/AccountTreeRounded";
import AutoAwesomeRounded from "@mui/icons-material/AutoAwesomeRounded";
import SettingsRounded from "@mui/icons-material/SettingsRounded";
import ShieldRounded from "@mui/icons-material/ShieldRounded";
import TimelineRounded from "@mui/icons-material/TimelineRounded";
import {
  Alert, Box, Card, CardContent, Chip, Divider, Grid, Stack, Tab, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, Tabs, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import { useState, type ReactNode } from "react";
import { useApi } from "../../api/client";
import { ErrorState, fmtDateTime, Loading, PageHeader, Section, timeAgo, titleCase } from "../../components/common";
import { FlowDiagram, KIND_STYLE, type Workflow } from "../../components/FlowDiagram";

interface Agent {
  id: string; name: string; module: string; kind: "LLM" | "DETERMINISTIC"; purpose: string; how_it_works: string[];
  inputs: string[]; outputs: string[]; guardrails: string[]; used_by: string[];
  activity_counts: { total: number; last_24h: number; last_at: string | null };
}
interface Component { name: string; module: string; purpose: string }
interface RecentEvent { id: string; occurred_at: string; action: string; outcome: string; actor_email: string | null; actor_role: string | null; patient_id: string | null; agents: string[]; summary: string }
interface AgentsResponse {
  window_days: number;
  config: {
    llm: {
      provider_configured: string; provider_active: string; model_active: string; fallback_active: boolean;
      claude_model: string; claude_effort: string; anthropic_api_key_set: boolean; openai_model: string; openai_api_key_set: boolean;
      ollama_base_url: string; ollama_model: string; timeout_seconds: number; prompt_version: string;
    };
    rag: { embedding_provider: string; embedding_dim: number; top_k: number; min_score: number };
  };
  agents: Agent[]; components: Component[]; workflows: Workflow[]; recent: RecentEvent[];
  assistant: {
    responses: number; llm_calls: number; answered_from_content: number; validation_failures: number;
    median_latency_ms: number | null; tokens: { input: number; output: number };
    by_provider: Record<string, number>; by_safety_level: Record<string, number>; by_intent: Record<string, number>;
  };
}


export default function AiAgentsPage() {
  const [tab, setTab] = useState(0);
  const [days, setDays] = useState(30);
  const { data, error, loading, reload } = useApi<AgentsResponse>(`/admin/ai-agents?days=${days}`, [days]);
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorState message={error ?? ""} onRetry={reload} />;
  const names = Object.fromEntries(data.agents.map((a) => [a.id, a.name]));

  return (
    <Stack gap={2}>
      <PageHeader title="AI agents" subtitle="What each agent does, how the workflows run, how AI is configured, and what the agents have done." />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" allowScrollButtonsMobile aria-label="AI agent sections">
        <Tab icon={<SettingsRounded />} iconPosition="start" label="Configuration" />
        <Tab icon={<AutoAwesomeRounded />} iconPosition="start" label={`Agents (${data.agents.length})`} />
        <Tab icon={<AccountTreeRounded />} iconPosition="start" label="Workflows" />
        <Tab icon={<TimelineRounded />} iconPosition="start" label="Activity" />
      </Tabs>
      {tab === 0 && <ConfigTab data={data} />}
      {tab === 1 && <AgentsTab agents={data.agents} />}
      {tab === 2 && <Stack gap={2}>{data.workflows.map((w) => <FlowDiagram key={w.id} wf={w} names={names} />)}</Stack>}
      {tab === 3 && <ActivityTab data={data} names={names} days={days} setDays={setDays} />}
    </Stack>
  );
}

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <Table size="small">
      <TableBody>
        {rows.map(([k, v]) => (
          <TableRow key={k}>
            <TableCell sx={{ color: "text.secondary", width: "45%" }}>{k}</TableCell>
            <TableCell><Typography variant="body2" fontWeight={600} component="span">{v}</Typography></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

const keyChip = (set: boolean) => <Chip size="small" label={set ? "Set" : "Not set"} color={set ? "success" : "default"} variant="outlined" />;

function ConfigTab({ data }: { data: AgentsResponse }) {
  const { llm, rag } = data.config;
  return (
    <Stack gap={2}>
      {llm.fallback_active ? (
        <Alert severity="warning">
          <strong>{titleCase(llm.provider_configured)}</strong> is configured but not available, so the assistant is using the
          offline <strong>{llm.provider_active}</strong> provider (it quotes approved content verbatim).
          {llm.provider_configured === "claude" && !llm.anthropic_api_key_set && <> To enable Claude, set <code>ANTHROPIC_API_KEY</code> in <code>.env</code> and restart with <code>make up</code>.</>}
        </Alert>
      ) : (
        <Alert severity="success">The assistant is using <strong>{llm.provider_active}</strong> ({llm.model_active}).</Alert>
      )}
      <Alert severity="info">Configuration is read-only here. It comes from environment variables in <code>.env</code>; API keys are never shown.</Alert>
      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Section title="LLM provider" icon={<AutoAwesomeRounded color="primary" />}>
            <KV rows={[
              ["Configured (LLM_PROVIDER)", llm.provider_configured],
              ["Active now", llm.provider_active],
              ["Active model", llm.model_active],
              ["Prompt version", llm.prompt_version],
              ["Timeout", `${llm.timeout_seconds} s`],
              ["Fallback", "extractive (offline, verbatim quotes)"],
            ]} />
          </Section>
        </Grid>
        <Grid item xs={12} md={6}>
          <Section title="Claude (Anthropic)" icon={<AutoAwesomeRounded sx={{ color: "#6941c6" }} />}>
            <KV rows={[
              ["Model (CLAUDE_MODEL)", llm.claude_model],
              ["Effort (CLAUDE_EFFORT)", llm.claude_effort],
              ["ANTHROPIC_API_KEY", keyChip(llm.anthropic_api_key_set)],
              ["Used by", "Patient Education Agent"],
            ]} />
          </Section>
        </Grid>
        <Grid item xs={12} md={6}>
          <Section title="Other providers">
            <KV rows={[
              ["OpenAI model", llm.openai_model],
              ["OPENAI_API_KEY", keyChip(llm.openai_api_key_set)],
              ["Ollama URL", llm.ollama_base_url],
              ["Ollama model", llm.ollama_model],
            ]} />
          </Section>
        </Grid>
        <Grid item xs={12} md={6}>
          <Section title="Retrieval (RAG)">
            <KV rows={[
              ["Embedding provider", rag.embedding_provider],
              ["Embedding dimension", rag.embedding_dim],
              ["Top K sources", rag.top_k],
              ["Minimum match score", rag.min_score],
            ]} />
          </Section>
        </Grid>
      </Grid>
      <Section title="Supporting components" icon={<ShieldRounded color="primary" />}>
        <Table size="small">
          <TableHead><TableRow><TableCell>Component</TableCell><TableCell>Module</TableCell><TableCell>Purpose</TableCell></TableRow></TableHead>
          <TableBody>
            {data.components.map((c) => (
              <TableRow key={c.name}>
                <TableCell><Typography variant="body2" fontWeight={600}>{c.name}</Typography></TableCell>
                <TableCell><code>{c.module}</code></TableCell>
                <TableCell>{c.purpose}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Section>
    </Stack>
  );
}

function ListBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" fontWeight={700} textTransform="uppercase">{title}</Typography>
      <Box component="ul" sx={{ m: 0, pl: 2.5 }}>{items.map((i) => <li key={i}><Typography variant="body2">{i}</Typography></li>)}</Box>
    </Box>
  );
}

function AgentsTab({ agents }: { agents: Agent[] }) {
  return (
    <Grid container spacing={2}>
      {agents.map((a) => (
        <Grid item xs={12} lg={6} key={a.id}>
          <Card id={`agent-${a.id}`} sx={{ height: "100%", borderColor: a.kind === "LLM" ? KIND_STYLE.llm.border : undefined, borderWidth: a.kind === "LLM" ? 2 : undefined }}>
            <CardContent>
              <Stack direction="row" justifyContent="space-between" alignItems="flex-start" gap={1}>
                <Box>
                  <Typography variant="h6" component="h2">{a.name} Agent</Typography>
                  <Typography variant="caption" color="text.secondary"><code>{a.module}</code></Typography>
                </Box>
                <Chip size="small" icon={a.kind === "LLM" ? <AutoAwesomeRounded /> : <ShieldRounded />}
                  label={a.kind === "LLM" ? "Uses LLM (bounded)" : "Deterministic"}
                  sx={a.kind === "LLM" ? { bgcolor: KIND_STYLE.llm.bg, color: "#5925dc" } : undefined} />
              </Stack>
              <Typography mt={1.5}><strong>Purpose:</strong> {a.purpose}</Typography>
              <Typography variant="caption" color="text.secondary" fontWeight={700} textTransform="uppercase" display="block" mt={1.5}>How it works</Typography>
              <Box component="ol" sx={{ m: 0, pl: 2.5 }}>{a.how_it_works.map((s) => <li key={s}><Typography variant="body2">{s}</Typography></li>)}</Box>
              <Grid container spacing={1.5} mt={0.5}>
                <Grid item xs={6}><ListBlock title="Inputs" items={a.inputs} /></Grid>
                <Grid item xs={6}><ListBlock title="Outputs" items={a.outputs} /></Grid>
                <Grid item xs={6}><ListBlock title="Guardrails" items={a.guardrails} /></Grid>
                <Grid item xs={6}><ListBlock title="Used by" items={a.used_by} /></Grid>
              </Grid>
              <Divider sx={{ my: 1.5 }} />
              <Typography variant="body2" color="text.secondary">
                Activity: <strong>{a.activity_counts.total}</strong> in window · <strong>{a.activity_counts.last_24h}</strong> in last 24 h
                {a.activity_counts.last_at ? ` · last ${timeAgo(a.activity_counts.last_at)}` : " · no activity yet"}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      ))}
    </Grid>
  );
}

function Counts({ title, data }: { title: string; data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  return (
    <Section title={title}>
      <Table size="small">
        <TableBody>
          {entries.length === 0 && <TableRow><TableCell colSpan={2}>No data</TableCell></TableRow>}
          {entries.map(([k, v]) => <TableRow key={k}><TableCell>{titleCase(k)}</TableCell><TableCell align="right">{v}</TableCell></TableRow>)}
        </TableBody>
      </Table>
    </Section>
  );
}

function ActivityTab({ data, names, days, setDays }: { data: AgentsResponse; names: Record<string, string>; days: number; setDays: (d: number) => void }) {
  const a = data.assistant;
  const [agentFilter, setAgentFilter] = useState<string | null>(null);
  const recent = agentFilter ? data.recent.filter((e) => e.agents.includes(agentFilter)) : data.recent;
  const pct = (n: number) => (a.responses ? `${Math.round((n / a.responses) * 100)}%` : "—");
  return (
    <Stack gap={2}>
      <Stack direction="row" alignItems="center" gap={1.5} flexWrap="wrap">
        <Typography variant="body2" color="text.secondary">Window</Typography>
        <ToggleButtonGroup size="small" exclusive value={days} onChange={(_, v) => v && setDays(v)} aria-label="Activity window">
          {[1, 7, 30, 90].map((d) => <ToggleButton key={d} value={d}>{d === 1 ? "24 h" : `${d} days`}</ToggleButton>)}
        </ToggleButtonGroup>
      </Stack>
      <Grid container spacing={2}>
        {([
          ["Assistant responses", a.responses],
          ["LLM calls", a.llm_calls],
          ["Answered from approved content", pct(a.answered_from_content)],
          ["Validation failures (fell back)", a.validation_failures],
          ["Median latency", a.median_latency_ms != null ? `${Math.round(a.median_latency_ms)} ms` : "—"],
          ["LLM tokens (in / out)", `${a.tokens.input} / ${a.tokens.output}`],
        ] as [string, ReactNode][]).map(([label, v]) => (
          <Grid item xs={6} md={4} lg={2} key={label}>
            <Card sx={{ height: "100%" }}><CardContent>
              <Typography variant="body2" color="text.secondary">{label}</Typography>
              <Typography variant="h5" component="p">{v}</Typography>
            </CardContent></Card>
          </Grid>
        ))}
      </Grid>
      <Section title="Activity per agent">
        <TableContainer>
          <Table size="small">
            <TableHead><TableRow><TableCell>Agent</TableCell><TableCell>Type</TableCell><TableCell align="right">In window</TableCell><TableCell align="right">Last 24 h</TableCell><TableCell>Last activity</TableCell></TableRow></TableHead>
            <TableBody>
              {data.agents.map((ag) => (
                <TableRow key={ag.id}>
                  <TableCell><Typography variant="body2" fontWeight={600}>{ag.name}</Typography></TableCell>
                  <TableCell>{ag.kind === "LLM" ? "LLM (bounded)" : "Deterministic"}</TableCell>
                  <TableCell align="right">{ag.activity_counts.total}</TableCell>
                  <TableCell align="right">{ag.activity_counts.last_24h}</TableCell>
                  <TableCell>{ag.activity_counts.last_at ? fmtDateTime(ag.activity_counts.last_at) : "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Section>
      <Grid container spacing={2}>
        <Grid item xs={12} md={4}><Counts title="Responses by provider" data={a.by_provider} /></Grid>
        <Grid item xs={12} md={4}><Counts title="Responses by safety level" data={a.by_safety_level} /></Grid>
        <Grid item xs={12} md={4}><Counts title="Responses by intent" data={a.by_intent} /></Grid>
      </Grid>
      <Section title="Recent agent activity">
        <Typography variant="body2" color="text.secondary" mb={1}>Latest events per agent, from the audit trail. Open <strong>Audit trail</strong> for full details of any event.</Typography>
        <Stack direction="row" gap={0.75} flexWrap="wrap" mb={1.5} aria-label="Filter by agent">
          <Chip label="All agents" clickable color={agentFilter ? "default" : "primary"} onClick={() => setAgentFilter(null)} />
          {data.agents.map((ag) => (
            <Chip key={ag.id} label={ag.name} clickable color={agentFilter === ag.id ? "primary" : "default"}
              onClick={() => setAgentFilter(ag.id)} disabled={ag.activity_counts.total === 0} />
          ))}
        </Stack>
        <TableContainer>
          <Table size="small">
            <TableHead><TableRow><TableCell>Time</TableCell><TableCell>Action</TableCell><TableCell>Agents</TableCell><TableCell>Summary</TableCell><TableCell>Actor</TableCell><TableCell>Patient</TableCell></TableRow></TableHead>
            <TableBody>
              {recent.length === 0 && <TableRow><TableCell colSpan={6}>No agent activity in this window</TableCell></TableRow>}
              {recent.map((e) => (
                <TableRow key={e.id} hover>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>{fmtDateTime(e.occurred_at)}</TableCell>
                  <TableCell><Typography variant="body2" fontWeight={600}>{e.action}</Typography></TableCell>
                  <TableCell>
                    <Stack direction="row" gap={0.5} flexWrap="wrap">
                      {e.agents.map((id) => <Chip key={id} size="small" label={names[id] ?? id} />)}
                    </Stack>
                  </TableCell>
                  <TableCell>{e.summary}</TableCell>
                  <TableCell>{e.actor_email ?? "system"}<Typography variant="caption" display="block" color="text.secondary">{e.actor_role}</Typography></TableCell>
                  <TableCell><Typography variant="caption">{e.patient_id?.slice(0, 8) ?? "—"}</Typography></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Section>
    </Stack>
  );
}
