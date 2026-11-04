import { Navigate, Route, Routes } from "react-router-dom";
import { homeFor, useAuth } from "./auth/AuthContext";
import { Loading } from "./components/common";
import Layout from "./components/Layout";
import AiAgentsPage from "./pages/admin/AiAgents";
import AnalyticsPage from "./pages/admin/Analytics";
import AuditPage from "./pages/admin/Audit";
import DemoPage from "./pages/admin/Demo";
import DocumentsPage from "./pages/admin/Documents";
import IntegrationsPage from "./pages/admin/Integrations";
import UsersPage from "./pages/admin/Users";
import CaregiverHome from "./pages/caregiver/CaregiverHome";
import Escalations from "./pages/careteam/Escalations";
import PatientDetail from "./pages/careteam/PatientDetail";
import PatientsList from "./pages/careteam/PatientsList";
import PlanApprovals from "./pages/careteam/PlanApprovals";
import Transport from "./pages/careteam/Transport";
import Protocols from "./pages/careteam/Protocols";
import Worklist from "./pages/careteam/Worklist";
import Login from "./pages/Login";
import Appointments from "./pages/patient/Appointments";
import Assistant from "./pages/patient/Assistant";
import Caregivers from "./pages/patient/Caregivers";
import Checkin from "./pages/patient/Checkin";
import Education from "./pages/patient/Education";
import Medications from "./pages/patient/Medications";
import Messages from "./pages/patient/Messages";
import PatientHome from "./pages/patient/PatientHome";
import RecoveryPlan from "./pages/patient/RecoveryPlan";
import Surveys from "./pages/patient/Surveys";

function Guard({ roles, children }: { roles: string[]; children: JSX.Element }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (!roles.includes(user.role)) return <Navigate to={homeFor(user.role)} replace />;
  return children;
}

const STAFF = ["NURSE", "SURGEON"];

export default function App() {
  const { user, ready } = useAuth();
  if (!ready) return <Loading />;
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to={homeFor(user.role)} replace /> : <Login />} />
      <Route element={user ? <Layout /> : <Navigate to="/login" replace />}>
        <Route path="/patient" element={<Guard roles={["PATIENT"]}><PatientHome /></Guard>} />
        <Route path="/patient/checkin" element={<Guard roles={["PATIENT"]}><Checkin /></Guard>} />
        <Route path="/patient/medications" element={<Guard roles={["PATIENT"]}><Medications /></Guard>} />
        <Route path="/patient/assistant" element={<Guard roles={["PATIENT"]}><Assistant /></Guard>} />
        <Route path="/patient/plan" element={<Guard roles={["PATIENT"]}><RecoveryPlan /></Guard>} />
        <Route path="/patient/appointments" element={<Guard roles={["PATIENT"]}><Appointments /></Guard>} />
        <Route path="/patient/education" element={<Guard roles={["PATIENT"]}><Education /></Guard>} />
        <Route path="/patient/messages" element={<Guard roles={["PATIENT"]}><Messages /></Guard>} />
        <Route path="/patient/caregivers" element={<Guard roles={["PATIENT"]}><Caregivers /></Guard>} />
        <Route path="/patient/surveys" element={<Guard roles={["PATIENT"]}><Surveys /></Guard>} />
        <Route path="/caregiver" element={<Guard roles={["CAREGIVER"]}><CaregiverHome /></Guard>} />
        <Route path="/care-team" element={<Guard roles={STAFF}><Worklist /></Guard>} />
        <Route path="/care-team/patients" element={<Guard roles={[...STAFF, "ADMIN"]}><PatientsList /></Guard>} />
        <Route path="/care-team/patients/:id" element={<Guard roles={STAFF}><PatientDetail /></Guard>} />
        <Route path="/care-team/transport" element={<Guard roles={["NURSE"]}><Transport /></Guard>} />
        <Route path="/care-team/protocols" element={<Guard roles={[...STAFF, "ADMIN"]}><Protocols /></Guard>} />
        <Route path="/surgeon" element={<Guard roles={["SURGEON"]}><Escalations /></Guard>} />
        <Route path="/surgeon/approvals" element={<Guard roles={["SURGEON"]}><PlanApprovals /></Guard>} />
        <Route path="/admin/analytics" element={<Guard roles={["ADMIN", "NURSE"]}><AnalyticsPage /></Guard>} />
        <Route path="/admin/documents" element={<Guard roles={["ADMIN", "SURGEON"]}><DocumentsPage /></Guard>} />
        <Route path="/admin/users" element={<Guard roles={["ADMIN"]}><UsersPage /></Guard>} />
        <Route path="/admin/ai-agents" element={<Guard roles={["ADMIN"]}><AiAgentsPage /></Guard>} />
        <Route path="/admin/integrations" element={<Guard roles={["ADMIN"]}><IntegrationsPage /></Guard>} />
        <Route path="/admin/audit" element={<Guard roles={["ADMIN"]}><AuditPage /></Guard>} />
        <Route path="/admin/demo" element={<Guard roles={["ADMIN", "NURSE"]}><DemoPage /></Guard>} />
      </Route>
      <Route path="*" element={<Navigate to={user ? homeFor(user.role) : "/login"} replace />} />
    </Routes>
  );
}
