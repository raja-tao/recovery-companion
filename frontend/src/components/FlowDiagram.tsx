import AccountTreeRounded from "@mui/icons-material/AccountTreeRounded";
import ArrowDownwardRounded from "@mui/icons-material/ArrowDownwardRounded";
import CallSplitRounded from "@mui/icons-material/CallSplitRounded";
import { Box, Chip, Stack, Typography } from "@mui/material";
import type { ReactNode } from "react";
import { severityColors } from "../theme";
import { Section } from "./common";

export type StepKind = "start" | "step" | "decision" | "llm" | "end";
export interface Branch { when: string; outcome: string; kind: StepKind; agent?: string }
export interface Step { label: string; detail?: string; kind: StepKind; agent?: string; branches?: Branch[] }
export interface Workflow { id: string; title: string; summary: string; steps: Step[] }

/** Box colors per flow-step kind. LLM steps are the only ones in purple, so model use stands out. */
export const KIND_STYLE: Record<StepKind, { bg: string; border: string; label: string }> = {
  start: { bg: "#f2f4f7", border: "#98a2b3", label: "Start" },
  step: { bg: "#ffffff", border: "#d0d5dd", label: "Step" },
  decision: { bg: severityColors.AMBER.bg, border: severityColors.AMBER.border, label: "Decision" },
  llm: { bg: "#f4f3ff", border: "#9b8afb", label: "LLM" },
  end: { bg: severityColors.GREEN.bg, border: severityColors.GREEN.border, label: "Result" },
};

function AgentChip({ id, names }: { id?: string; names: Record<string, string> }) {
  if (!id) return null;
  return <Chip size="small" variant="outlined" label={`${names[id] ?? id} Agent`} sx={{ mt: 0.5, bgcolor: "#fff" }} />;
}

function FlowBox({ kind, children, minWidth = 0 }: { kind: StepKind; children: ReactNode; minWidth?: number }) {
  const s = KIND_STYLE[kind];
  return (
    <Box sx={{
      bgcolor: s.bg, border: `2px ${kind === "decision" ? "dashed" : "solid"} ${s.border}`, borderRadius: kind === "start" || kind === "end" ? 6 : 2,
      px: 2, py: 1.25, minWidth, maxWidth: 520, width: "100%",
    }}>
      <Typography variant="caption" fontWeight={700} color="text.secondary" textTransform="uppercase">{s.label}</Typography>
      {children}
    </Box>
  );
}

const Arrow = () => <ArrowDownwardRounded sx={{ color: "#98a2b3", my: 0.25 }} aria-hidden />;

/** Vertical flow chart: steps top to bottom; a decision fans out to its branches before the flow continues. */
export function FlowDiagram({ wf, names = {} }: { wf: Workflow; names?: Record<string, string> }) {
  return (
    <Section title={wf.title} id={`wf-${wf.id}`} icon={<AccountTreeRounded color="primary" />}>
      <Typography color="text.secondary" mb={2}>{wf.summary}</Typography>
      <Stack direction="row" gap={1} flexWrap="wrap" mb={2} aria-label="Legend">
        {(Object.keys(KIND_STYLE) as StepKind[]).map((k) => (
          <Chip key={k} size="small" label={KIND_STYLE[k].label}
            sx={{ bgcolor: KIND_STYLE[k].bg, border: `1px ${k === "decision" ? "dashed" : "solid"} ${KIND_STYLE[k].border}` }} />
        ))}
      </Stack>
      <Stack alignItems="center" role="list" aria-label={`${wf.title} steps`}>
        {wf.steps.map((s, i) => (
          <Stack key={i} alignItems="center" width="100%" role="listitem">
            {i > 0 && <Arrow />}
            <FlowBox kind={s.kind}>
              <Typography fontWeight={700}>{i + 1}. {s.label}</Typography>
              {s.detail && <Typography variant="body2" color="text.secondary">{s.detail}</Typography>}
              <AgentChip id={s.agent} names={names} />
            </FlowBox>
            {s.branches && (
              <>
                <CallSplitRounded sx={{ color: "#98a2b3", my: 0.25, transform: "rotate(180deg)" }} aria-hidden />
                <Box sx={{ display: "grid", gap: 1, width: "100%", gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)", lg: `repeat(${Math.min(s.branches.length, 3)}, 1fr)` } }}>
                  {s.branches.map((b) => (
                    <FlowBox key={b.when} kind={b.kind}>
                      <Typography variant="body2" fontWeight={700}>If {b.when}</Typography>
                      <Typography variant="body2">→ {b.outcome}</Typography>
                      <AgentChip id={b.agent} names={names} />
                    </FlowBox>
                  ))}
                </Box>
              </>
            )}
          </Stack>
        ))}
      </Stack>
    </Section>
  );
}
