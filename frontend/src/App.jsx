import { useEffect, useMemo, useRef , useState } from 'react';
import { getJson, postJson, putJson } from './api';
import SiemensLoginScreen from './components/SiemensLogin';
import ProfileCreationScreen from './components/ProfileCreation';

const VIEWS = [
  'overview',
  'employee',
  'manager',
  'intelligence',
  'profile-creation',
  'resume-output',
  'skill-output',
  'market-output',
  'career-output',
  'roadmap-output',
  'talent-output',
  'data',
  'profile',
];
const NAV_ITEMS = [
  { key: 'overview', label: 'Overview' },
  { key: 'employee', label: 'Employee Studio' },
  { key: 'manager', label: 'Manager Console' },
  { key: 'intelligence', label: 'Intelligence Hub' },
  { key: 'profile-creation', label: 'Complete Profile' },
  { key: 'resume-output', label: 'Resume Output' },
  { key: 'skill-output', label: 'Skill Output' },
  { key: 'market-output', label: 'Market Output' },
  { key: 'career-output', label: 'Career Output' },
  { key: 'roadmap-output', label: 'Roadmap Output' },
  { key: 'talent-output', label: 'Talent Output' },
  { key: 'data', label: 'Raw Data' },
  {key: 'profile', label: 'Profile' },
];

const EXECUTION_STAGES = ['resume', 'skill', 'market', 'career', 'learning', 'talent', 'workflow', 'health'];

const STAGE_LABELS = {
  resume: 'Resume',
  skill: 'Skill',
  market: 'Market',
  career: 'Career',
  learning: 'Learning',
  talent: 'Talent',
  workflow: 'Workflow',
  health: 'Health',
};

const VIEW_STORAGE_KEY = 'siemens_workforce_active_view';

function parseError(error) {
  if (!error) return 'Request failed.';
  if (typeof error === 'string') return error;
  const message = error.message || 'Request failed.';
  try {
    const payload = JSON.parse(message);
    if (payload?.detail) return String(payload.detail);
  } catch {
    // Keep original message when not JSON.
  }
  return message;
}

function compactNumber(value) {
  if (value === null || value === undefined || value === '') return '-';
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return Number.isInteger(num) ? String(num) : num.toFixed(2);
}

function sanitizeSkillList(skills) {
  if (!Array.isArray(skills)) return [];
  return skills.map((skill) => String(skill || '').trim()).filter(Boolean);
}

function mergeGaps(skillResult, marketResult) {
  const core = Array.isArray(skillResult?.core_gaps) ? skillResult.core_gaps : [];
  const market = Array.isArray(marketResult?.market_gaps) ? marketResult.market_gaps : [];
  return Array.from(new Set([...core, ...market].map((item) => String(item || '').trim()).filter(Boolean)));
}

function extractWorkflowAnalysis(payload) {
  if (!payload || typeof payload !== 'object') return {};
  return payload.analysis && typeof payload.analysis === 'object' ? payload.analysis : payload;
}

function getSourceHealthRows(marketData) {
  const sourceHealth = marketData?.source_health;
  if (!sourceHealth || typeof sourceHealth !== 'object') return [];

  return Object.entries(sourceHealth).map(([name, value]) => ({
    name,
    status: value?.status || (value ? 'active' : 'inactive'),
    count: value?.count ?? value?.items ?? '-',
  }));
}

function normalizeRoadmapPayload(roadmapData) {
  if (!roadmapData || typeof roadmapData !== 'object') return null;

  const phaseSource = roadmapData.learning_path?.phases || {};
  const projectSource = roadmapData.project_roadmap || roadmapData.projects || {};

  return {
    ...roadmapData,
    foundation: roadmapData.foundation || phaseSource.foundation || { duration_weeks: 0, skills: [], description: '' },
    core: roadmapData.core || phaseSource.core || { duration_weeks: 0, skills: [], description: '' },
    advanced: roadmapData.advanced || phaseSource.advanced || { duration_weeks: 0, skills: [], description: '' },
    projects: roadmapData.projects || {
      ...projectSource,
      details: Array.isArray(projectSource?.details)
        ? projectSource.details
        : Array.isArray(projectSource?.projects)
          ? projectSource.projects
          : [],
    },
  };
}

function getRoadmapPhases(roadmapData) {
  const foundationWeeks = Number(roadmapData?.foundation?.duration_weeks || 0);
  const coreWeeks = Number(roadmapData?.core?.duration_weeks || 0);
  const advancedWeeks = Number(roadmapData?.advanced?.duration_weeks || 0);
  const total = foundationWeeks + coreWeeks + advancedWeeks;

  const normalize = (weeks) => {
    if (!total) return 0;
    return Math.max(8, Math.round((weeks / total) * 100));
  };

  return [
    { key: 'foundation', label: 'Foundation', weeks: foundationWeeks, width: normalize(foundationWeeks) },
    { key: 'core', label: 'Core Build', weeks: coreWeeks, width: normalize(coreWeeks) },
    { key: 'advanced', label: 'Advanced', weeks: advancedWeeks, width: normalize(advancedWeeks) },
  ];
}

function deriveMatchName(item, index) {
  if (!item || typeof item !== 'object') return `Candidate ${index + 1}`;
  return item.employee_name || item.name || item.employee || item.id || `Candidate ${index + 1}`;
}

function deriveMatchScore(item) {
  if (!item || typeof item !== 'object') return '-';
  const raw = item.match_percentage ?? item.match_score ?? item.score ?? item.similarity;
  const value = Number(raw);
  if (!Number.isFinite(value)) return '-';
  return `${compactNumber(value)}%`;
}

function deriveMatchPercentValue(item) {
  if (!item || typeof item !== 'object') return 0;
  const raw = item.match_percentage ?? item.match_score ?? item.score ?? item.similarity;
  const value = Number(raw);
  if (!Number.isFinite(value)) return 0;
  return Math.min(100, Math.max(0, value));
}

function deriveMissingSkills(item) {
  if (!item || typeof item !== 'object') return [];
  if (Array.isArray(item.missing_skills)) return item.missing_skills;
  if (Array.isArray(item.missingSkills)) return item.missingSkills;
  return [];
}

function readInitialView() {
  const hash = window.location.hash.replace('#', '').trim().toLowerCase();
  if (VIEWS.includes(hash)) return hash;
  const stored = window.localStorage.getItem(VIEW_STORAGE_KEY)?.trim().toLowerCase();
  if (stored && VIEWS.includes(stored)) return stored;
  return 'overview';
}

function setViewHash(view) {
  window.location.hash = view;
  window.localStorage.setItem(VIEW_STORAGE_KEY, view);
}

function getStageLabel(stage) {
  return STAGE_LABELS[stage] || stage || 'idle';
}

function ActionDiagramIcon({ variant }) {
  return (
    <span className="action-icon" aria-hidden="true">
      {variant === 'people' && (
        <svg viewBox="0 0 48 48" role="presentation" focusable="false">
          <circle cx="18" cy="16" r="4.5" />
          <circle cx="31" cy="18" r="3.5" />
          <path d="M11 35c0-5 3.8-8 7-8s7 3 7 8" />
          <path d="M24 34c0-3.5 2.6-6 5.5-6S35 30.5 35 34" />
          <path d="M8 38h32" />
          <path d="M14 26h8" />
          <path d="M28 26h6" />
        </svg>
      )}
      {variant === 'capacity' && (
        <svg viewBox="0 0 48 48" role="presentation" focusable="false">
          <rect x="8" y="12" width="32" height="8" rx="1.5" />
          <rect x="8" y="24" width="24" height="8" rx="1.5" />
          <rect x="8" y="36" width="18" height="4" rx="1.2" />
          <path d="M31 27l5 5 5-5" />
          <path d="M31 39l5-5 5 5" />
        </svg>
      )}
      {variant === 'signals' && (
        <svg viewBox="0 0 48 48" role="presentation" focusable="false">
          <path d="M10 34h8l4-16 4 12 4-8 4 12h4" />
          <circle cx="14" cy="34" r="2" />
          <circle cx="22" cy="18" r="2" />
          <circle cx="30" cy="22" r="2" />
          <circle cx="34" cy="30" r="2" />
        </svg>
      )}
      {variant === 'audit' && (
        <svg viewBox="0 0 48 48" role="presentation" focusable="false">
          <path d="M14 8h16l6 6v24H14z" />
          <path d="M30 8v6h6" />
          <path d="M18 22h12" />
          <path d="M18 28h8" />
          <circle cx="30" cy="31" r="4" />
          <path d="M33 34l4 4" />
        </svg>
      )}
    </span>
  );
}

function SidebarNav({ view, onViewChange }) {
  return (
    <aside className="si-sidebar">
      <div className="si-sidebar-brand">
        <div className="si-logo-text">SIEMENS</div>
        <h1>Learning & Development</h1>
        <p>Skill gaps, growth paths, and talent matching</p>
      </div>

      <nav className="si-nav" aria-label="Primary">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={view === item.key ? 'active' : ''}
            onClick={() => onViewChange(item.key)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div className="si-sidebar-note">
        <span>Platform</span>
        <strong>Skill, growth & talent intelligence</strong>
      </div>
    </aside>
  );
}

function TopBar({ health, busy, activeStage, onRefresh, user, onLogout }) {
  return (
    <header className="si-topbar">
      <div className="si-topbar-title">
        <h2>Learning & Development Pathway</h2>
        <p>Skill readiness, growth roadmaps, and talent matching</p>
      </div>
      <div className="si-topbar-actions">
        {user && (
          <div className="user-profile">
            <div className="user-avatar">
              {(user.name || user.email || 'U').charAt(0).toUpperCase()}
            </div>
            <div className="user-info">
              <span className="user-name">{user.name || user.email}</span>
              <span className="user-role">{user.role || 'User'} {user.department ? ' - ' + user.department : ''}</span>
            </div>
            <button type="button" className="logout-btn" onClick={onLogout} title="Sign out">
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}

function KPI({ label, value, hint, outOf }) {
  const hasValue = value !== '-' && value !== '' && value !== null && value !== undefined;
  const display = outOf && hasValue ? `${value} / ${outOf}` : value;
  return (
    <article className="kpi-card">
      <span>{label}</span>
      <strong>{display}</strong>
      <small>{hint}</small>
    </article>
  );
}

function JsonPanel({ title, data }) {
  return (
    <section className="panel">
      <div className="panel-head"><h3>{title}</h3></div>
      <pre>{data ? JSON.stringify(data, null, 2) : 'No response yet.'}</pre>
    </section>
  );
}

function AgentOutputPage({ title, subtitle, data, emptyText, children }) {
  return (
    <section className="view-grid one-col">
      <section className="panel">
        <div className="panel-head panel-head-inline">
          <div>
            <h3>{title}</h3>
            <p className="panel-subtitle">{subtitle}</p>
          </div>
        </div>
        {children}
        {data && (
          <details className="raw-json-details">
            <summary className="raw-json-summary">Raw JSON (for debugging)</summary>
            <pre className="raw-json-pre">{JSON.stringify(data, null, 2)}</pre>
          </details>
        )}
        {!data && <p className="empty-text">{emptyText}</p>}
      </section>
    </section>
  );
}

function RoadmapTimeline({ roadmapData }) {
  const phases = getRoadmapPhases(roadmapData);

  return (
    <section className="panel">
      <div className="panel-head"><h3>Roadmap Timeline</h3></div>
      <div className="timeline-stack">
        {phases.map((phase) => (
          <div key={phase.key} className="timeline-row">
            <div className="timeline-meta">
              <span>{phase.label}</span>
              <strong>{compactNumber(phase.weeks)} weeks</strong>
            </div>
            <div className="timeline-bar">
              <div className={`timeline-fill phase-${phase.key}`} style={{ width: `${phase.width}%` }} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function MarketSourceHealth({ marketData }) {
  const rows = getSourceHealthRows(marketData);

  return (
    <section className="panel">
      <div className="panel-head"><h3>Market Source Health</h3></div>
      <div className="source-grid">
        {rows.length ? rows.map((row) => (
          <article key={row.name} className="source-card">
            <span>{row.name}</span>
            <strong>{row.status}</strong>
            <small>items: {compactNumber(row.count)}</small>
          </article>
        )) : <p className="empty-text">Run Market Agent to populate live source telemetry.</p>}
      </div>
    </section>
  );
}

function TalentPreview({ talentData, managerWorkflowData }) {
  const matches = useMemo(() => {
    if (Array.isArray(talentData?.matches)) return talentData.matches;
    if (Array.isArray(managerWorkflowData?.matches)) return managerWorkflowData.matches;
    return [];
  }, [managerWorkflowData, talentData]);

  return (
    <section className="panel">
      <div className="panel-head"><h3>Top Talent Matches</h3></div>
      <div className="match-list">
        {matches.length ? matches.slice(0, 5).map((item, index) => (
          <div className="match-row" key={`${deriveMatchName(item, index)}-${index}`}>
            <span>{deriveMatchName(item, index)}</span>
            <strong>{deriveMatchScore(item)}</strong>
          </div>
        )) : <p className="empty-text">Run Talent Match or Manager Workflow to see ranked candidates.</p>}
      </div>
    </section>
  );
}

function LoadingSpinner({ stage }) {
  return (
    <div className="loading-overlay">
      <div className="loading-container">
        <div className="spinner" />
        <h3>Analyzing Resume</h3>
        <p>Processing stage: <strong>{getStageLabel(stage)}</strong></p>
        <div className="progress-bar">
          <div className="progress-fill" />
        </div>
      </div>
    </div>
  );
}

function ErrorAlert({ message, onDismiss }) {
  return (
    <div className="error-alert">
      <div className="error-content">
        <strong>Error</strong>
        <p>{message}</p>
      </div>
      <button type="button" onClick={onDismiss} className="error-close">x</button>
    </div>
  );
}

function RoleSelectionDialog({ open, suggestions, onRoleSelect, onSkip, profileRole }) {
  if (!open) return null;
  
  const [selectedCategory, setSelectedCategory] = useState('');
  const [roleSearch, setRoleSearch] = useState('');
  const [selectedRoleFromDropdown, setSelectedRoleFromDropdown] = useState('');
  
  // Auto-select first relevant category on open
  useEffect(() => {
    const relevantCat = suggestions.find(c => c.is_relevant);
    if (relevantCat && !selectedCategory) {
      setSelectedCategory(relevantCat.category);
    }
  }, [open]);
  
  // Reset when modal closes
  useEffect(() => {
    if (!open) {
      setSelectedCategory('');
      setRoleSearch('');
      setSelectedRoleFromDropdown('');
    }
  }, [open]);
  
  const allRoles = suggestions.flatMap(cat =>
    cat.matched_roles.map(role => ({ role, category: cat.category, isRelevant: cat.is_relevant }))
  );
  
  const availableRoles = selectedCategory
    ? allRoles.filter(r => r.category === selectedCategory)
    : allRoles;
  
  const filteredRoles = roleSearch
    ? availableRoles.filter(r => 
        r.role.toLowerCase().includes(roleSearch.toLowerCase())
      )
    : availableRoles;
  
  // Check if profile role exists in list
  const profileRoleExists = profileRole && allRoles.some(r => 
    r.role.toLowerCase() === profileRole.toLowerCase()
  );
  
  const handleConfirm = () => {
    if (selectedRoleFromDropdown) {
      onRoleSelect(selectedRoleFromDropdown);
    }
  };
  
  return (
    <div className="modal-overlay">
      <div className="modal-dialog">
        <div className="modal-header">
          <h2>Confirm Your Role</h2>
          <p className="modal-subtitle">Help us personalize your skill analysis</p>
        </div>
        <div className="modal-body">
          <div className="detected-role-display">
            Detected role: <strong>"{profileRole || 'Unknown'}"</strong>
            {profileRoleExists && <span className="detected-badge"> (in list)</span>}
          </div>
          <p className="modal-hint">Please select your exact role from the dropdowns below:</p>
          <div className="role-dropdown-section">
            <label htmlFor="role-category-select" className="role-dropdown-label">Category:</label>
            <select 
              id="role-category-select"
              className="role-category-dropdown"
              value={selectedCategory}
              onChange={(e) => {
                setSelectedCategory(e.target.value);
                setRoleSearch('');
              }}
            >
              <option value="">All Categories</option>
              {suggestions.map((cat) => (
                <option key={cat.category} value={cat.category}>
                  {cat.is_relevant ? '★ ' : ''}{cat.icon} {cat.category} ({cat.matched_roles.length} roles)
                </option>
              ))}
            </select>
            <label htmlFor="role-search" className="role-dropdown-label">Specific Role:</label>
            <input
              id="role-search"
              type="text"
              className="role-search-input"
              placeholder="Search roles or select from dropdown..."
              value={roleSearch}
              onChange={(e) => setRoleSearch(e.target.value)}
            />
            <select 
              className="role-specific-dropdown"
              value={selectedRoleFromDropdown}
              onChange={(e) => setSelectedRoleFromDropdown(e.target.value)}
            >
              <option value="" disabled>Select a specific role</option>
              {profileRoleExists && (
                <option value={profileRole}>{profileRole} (Detected)</option>
              )}
              {filteredRoles.map(({ role }) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="modal-footer">
          <button
            type="button"
            className="secondary-btn"
            onClick={() => {
              if (profileRole) {
                onRoleSelect(profileRole);
              } else {
                onSkip();
              }
            }}
            disabled={!profileRole}
          >
            Use Detected Role
          </button>
          <button
            type="button"
            className="primary-btn"
            onClick={handleConfirm}
            disabled={!selectedRoleFromDropdown}
          >
            Confirm Role
          </button>
        </div>
      </div>
    </div>
  );
}

function SuccessAlert({ message }) {
  return (
    <div className="success-alert">
      <span>✅ {message}</span>
    </div>
  );
}

function SkillResultPanel({ skillData, currentRole, targetRole, busy }) {
  const payload = skillData?.skill_gap_json || skillData?.details || {};
  const gaps = Array.isArray(payload?.core_gaps) ? payload.core_gaps : (Array.isArray(skillData?.core_gaps) ? skillData.core_gaps : []);
  const gapsByHeading = payload?.core_gaps_by_heading && Object.keys(payload.core_gaps_by_heading).length > 0
    ? payload.core_gaps_by_heading
    : null;
  const score = Number(payload?.readiness_summary?.readiness_score ?? skillData?.readiness_score ?? 0);
  const details = payload;
  const summary = details?.readiness_summary || {};
  const matchedSkills = Array.isArray(details?.skill_analysis?.matched_skills)
    ? details.skill_analysis.matched_skills
    : [];
  const prioritySkills = Array.isArray(details?.skill_analysis?.priority_skills)
    ? details.skill_analysis.priority_skills
    : [];
  const immediateActions = Array.isArray(details?.recommendations?.immediate_actions)
    ? details.recommendations.immediate_actions
    : [];

  const effectiveTargetRole = (targetRole || '').trim() || (details?.user_profile?.target_role || '') || currentRole || '-';
  const effectiveCurrentRole = currentRole || details?.user_profile?.current_role || '-';

  return (
    <section className="panel skill-result-panel skill-result-panel-wide">
      <div className="panel-head">
        <h3>Skill Agent Results</h3>
      </div>

      <div className="skill-role-strip">
        <div><span>Current Role</span><strong>{effectiveCurrentRole}</strong></div>
        <div><span>Target Role</span><strong>{effectiveTargetRole}</strong></div>
        <div><span>Status</span><strong>{busy ? 'Running' : 'Ready'}</strong></div>
      </div>

      <div className="meta-list skill-summary-list">
        <div><span>Readiness Score</span><strong>{compactNumber(score)}</strong></div>
        <div><span>Readiness Category</span><strong>{summary?.readiness_category || '-'}</strong></div>
        <div><span>Expected Skills</span><strong>{compactNumber(summary?.total_skills_required ?? skillData?.expected_skills_count ?? '-')}</strong></div>
        <div><span>Core Gaps</span><strong>{compactNumber(gaps.length)}</strong></div>
        <div><span>Matched Skills</span><strong>{compactNumber(matchedSkills.length)}</strong></div>
        <div><span>Missing Skills</span><strong>{compactNumber(summary?.skills_missing ?? '-')}</strong></div>
      </div>

      <div className="skill-section-title">Skill Gaps by Category</div>
      {gapsByHeading ? (
        <div className="heading-gaps-list">
          {Object.entries(gapsByHeading).map(([heading, skills]) => (
            <div key={heading} className="heading-gap-group">
              <div className="heading-gap-title">{heading}</div>
              <div className="tag-wrap">
                {skills.map((skill, i) => <span className="tag tag-gap" key={`${heading}-${i}`}>{skill}</span>)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="tag-wrap">
          {gaps.length
            ? gaps.map((gap) => <span className="tag" key={gap}>{gap}</span>)
            : <span className="tag tag-muted">No gaps yet. Click Run Skill Agent to analyze.</span>}
        </div>
      )}

      {prioritySkills.length ? (
        <div className="skill-priority-list">
          {prioritySkills.slice(0, 6).map((item, index) => (
            <div key={`${item.skill}-${index}`} className="skill-priority-item">
              <span>{index + 1}. {item.skill}</span>
              <strong>{item.priority}</strong>
            </div>
          ))}
        </div>
      ) : null}

      <div className="skill-section-title">Immediate Actions</div>
      <div className="skill-action-list">
        {immediateActions.length
          ? immediateActions.slice(0, 3).map((action, index) => <div key={`${action}-${index}`}>{action}</div>)
          : <div>Run Skill Agent to generate action plan.</div>}
      </div>
    </section>
  );
}


function ResumeProfileView({ data, role }) {
  const profile = data?.profile || data?.extracted_profile || {};
  const skills = Array.isArray(profile.skills) ? profile.skills : (Array.isArray(data?.skills) ? data.skills : []);
  const experience = Number(profile.experience_years ?? data?.experience_years ?? 0);
  const extractedText = data?.extracted_text || '';
  const displayRole = String(role || '').trim();
  
  const skillCategories = {
    'Cloud & DevOps': skills.filter(s => /aws|azure|gcp|docker|kubernetes|k8s|jenkins|ci|cd|cloud|devops|terraform|ansible/i.test(s)),
    'Languages': skills.filter(s => /java|python|javascript|typescript|go|rust|cpp|c#|ruby|php|swift|kotlin|scala/i.test(s)),
    'Frameworks': skills.filter(s => /spring|spring boot|react|angular|vue|django|flask|express|node|next|nuxt/i.test(s)),
    'Databases': skills.filter(s => /sql|postgresql|mysql|mongodb|redis|elastic|kafka|database/i.test(s)),
    'Tools': skills.filter(s => /git|github|gitlab|bitbucket|jira|confluence|tools|linux|unix|postman|webpack|vite|figma/i.test(s)),
    'Methodologies & Soft Skills': skills.filter(s => /agile|kanban|scrum|communication|collaboration|leadership|stakeholder|mentoring|problem solving|analytical|teamwork|presentation|user.centered|ux|design thinking|wcag|accessibility|rest|performance/i.test(s)),
  };
  
  const categorized = Object.entries(skillCategories).filter(([_, items]) => items.length > 0);
  const uncategorized = skills.filter(s => !Object.values(skillCategories).flat().includes(s));
  if (uncategorized.length) {
    categorized.push(['Technologies', uncategorized]);
  }
  
  return (
    <section className="view-grid two-col">
      <section className="panel">
        <div className="panel-head"><h3>Extracted Profile</h3></div>
        <div className="profile-card">
          <div className="profile-avatar">
            {(profile.name || 'U').charAt(0).toUpperCase()}
          </div>
          <div className="profile-details">
            <h4>{profile.name || 'Unknown'}</h4>
            <p>{displayRole || 'Enter a target role to set your role'}</p>
            <span className="profile-exp">{experience} years experience</span>
          </div>
        </div>
        {profile.email && <div className="profile-meta"><span>Email</span><strong>{profile.email}</strong></div>}
        {profile.department && <div className="profile-meta"><span>Department</span><strong>{profile.department}</strong></div>}
        
        {extractedText && (
          <>
            <div className="panel-head" style={{ marginTop: '24px' }}><h3>Resume Text</h3></div>
            <div className="resume-text-box">
              {extractedText}
            </div>
          </>
        )}
      </section>
      
      <section className="panel">
        <div className="panel-head"><h3>Detected Skills</h3></div>
        <div className="skill-count-badge">{skills.length} skills found</div>
        
        {categorized.length > 0 ? (
          <div className="skill-categories">
            {categorized.map(([category, items]) => (
              <div key={category} className="skill-category">
                <h4 className="skill-category-title">{category}</h4>
                <div className="tag-wrap">
                  {items.map((skill, i) => (
                    <span className="tag" key={`${category}-${i}`}>{skill}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="tag-wrap">
            {skills.map((skill, i) => <span className="tag" key={i}>{skill}</span>)}
          </div>
        )}
      </section>
    </section>
  );
}

function SkillGapDashboard({ data }) {
  const payload = data?.skill_gap_json || data?.details || {};
  const skillSource = payload?.skill_source || {};
  const score = Number(payload.readiness_summary?.readiness_score ?? data?.readiness_score ?? 0);
  const gaps = Array.isArray(payload.core_gaps) ? payload.core_gaps : (Array.isArray(data?.core_gaps) ? data.core_gaps : []);
  const gapsByHeading = payload?.core_gaps_by_heading && Object.keys(payload.core_gaps_by_heading).length > 0
    ? payload.core_gaps_by_heading
    : null;
  const matched = Array.isArray(payload.skill_analysis?.matched_skills) ? payload.skill_analysis.matched_skills : [];
  const missing = Number(payload.readiness_summary?.skills_missing ?? gaps.length);
  const total = Number(payload.readiness_summary?.total_skills_required ?? (matched.length + missing));
  
  const workbookFile = skillSource.workbook_file || '';
  const sheetName = skillSource.sheet || '';
  const sourceLabel = sheetName ? `Sheet: ${sheetName}` : (skillSource.source || '');
  
  return (
    <section className="view-grid two-col">
      <section className="panel">
        <div className="panel-head"><h3>Readiness Assessment</h3></div>
        {sourceLabel && (
          <div className="source-badge">
            <span className="source-label">Source:</span> {sourceLabel}
            {workbookFile && <span className="source-file"> ({workbookFile.split('/').pop().split('\\\\').pop()})</span>}
          </div>
        )}
        <div className="readiness-display">
          <div className="readiness-ring">
            <svg viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="40" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="8" />
              <circle cx="50" cy="50" r="40" fill="none" stroke={score >= 70 ? '#13a688' : score >= 40 ? '#0CC' : '#FF7687'} strokeWidth="8" strokeDasharray={`${score * 2.51} 251`} strokeLinecap="round" transform="rotate(-90 50 50)" />
              <text x="50" y="50" textAnchor="middle" dy="0.3em" fill="#fff" fontSize="20" fontWeight="700">{score}%</text>
            </svg>
          </div>
          <div className="readiness-info">
            <span className="readiness-category">{payload.readiness_summary?.readiness_category || 'Analyzing...'}</span>
            <small>Based on {total} required skills</small>
          </div>
        </div>
        <div className="skill-meters">
          <div className="meter"><span>Matched</span><div className="meter-bar"><div className="meter-fill meter-success" style={{ width: total ? `${(matched.length / total) * 100}%` : '0%' }} /></div><strong>{matched.length}</strong></div>
          <div className="meter"><span>Gaps</span><div className="meter-bar"><div className="meter-fill meter-danger" style={{ width: total ? `${(missing / total) * 100}%` : '0%' }} /></div><strong>{missing}</strong></div>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head"><h3>Core Skill Gaps</h3></div>
        {gapsByHeading ? (
          <div className="heading-gaps-list">
            {Object.entries(gapsByHeading).map(([heading, skills]) => (
              <div key={heading} className="heading-gap-group">
                <div className="heading-gap-title">{heading}</div>
                <div className="tag-wrap">
                  {skills.map((skill, i) => <span className="tag tag-gap" key={`${heading}-${i}`}>{skill}</span>)}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="gap-list">
            {gaps.length
              ? gaps.map((gap, i) => (
                  <div key={i} className="gap-item">
                    <span className="gap-number">{i + 1}</span>
                    <span className="gap-name">{gap}</span>
                  </div>
                ))
              : <p className="empty-text">No critical gaps identified. Run Skill Agent to analyze.</p>}
          </div>
        )}
      </section>
    </section>
  );
}

function MarketIntelligenceView({ data }) {
  const payload = (data && typeof data === 'object' ? (data.details && typeof data.details === 'object' ? data : data) : {}) || {};
  const gaps = Array.isArray(data?.market_gaps) ? data.market_gaps : (Array.isArray(payload?.market_gaps) ? payload.market_gaps : []);
  const industryTrending = Array.isArray(data?.industry_trending_skills)
    ? data.industry_trending_skills
    : (Array.isArray(payload?.industry_trending_skills)
      ? payload.industry_trending_skills
      : (Array.isArray(data?.trending_skills)
        ? data.trending_skills
        : (Array.isArray(payload?.trending_skills) ? payload.trending_skills : [])));
  const vanishing = Array.isArray(data?.vanishing_skills)
    ? data.vanishing_skills
    : (Array.isArray(payload?.vanishing_skills) ? payload.vanishing_skills : []);
  const roleSpecific = Array.isArray(data?.role_specific_trends)
    ? data.role_specific_trends
    : (Array.isArray(payload?.role_specific_trends) ? payload.role_specific_trends : []);
  const sourceHealth = (data?.source_health && typeof data.source_health === 'object')
    ? data.source_health
: ((payload?.source_health && typeof payload.source_health === 'object') ? payload.source_health : {});
  const sourceRows = Object.entries(sourceHealth);

  return (
    <section className="view-grid two-col">
      <section className="panel">
        <div className="panel-head" style={{ marginTop: '20px' }}><h3>Industry Trending Skills</h3></div>
        <div className="tag-wrap">
          {industryTrending.length
            ? industryTrending.map((skill, i) => <span className="tag tag-emerging" key={`industry-${i}`}>{skill}</span>)
            : <span className="tag tag-muted">No industry-level trends available yet.</span>}
        </div>

        <div className="panel-head" style={{ marginTop: '20px' }}><h3>Role-Specific Trends</h3></div>
        <div className="tag-wrap">
          {roleSpecific.length
            ? roleSpecific.map((skill, i) => <span className="tag" key={`role-${i}`}>{skill}</span>)
            : <span className="tag tag-muted">No role-specific trends detected for this profile.</span>}
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><h3>Market Demand Analysis</h3></div>
        <div className="market-stats">
          <div className="market-stat">
            <span className="market-stat-value">{industryTrending.length}</span>
            <span className="market-stat-label">Industry Trending Skills</span>
          </div>
          <div className="market-stat">
            <span className="market-stat-value">{roleSpecific.length}</span>
            <span className="market-stat-label">Role-Specific Trends</span>
          </div>
        </div>

        <div className="panel-head" style={{ marginTop: '20px' }}><h3>Source Health</h3></div>
        <div className="source-grid">
          {sourceRows.length ? sourceRows.map(([name, value]) => (
            <article key={name} className="source-card">
              <span>{name}</span>
              <strong>{String(value?.status || '-')}</strong>
              <small>items: {compactNumber(value?.count ?? 0)}</small>
            </article>
          )) : <p className="empty-text">Run Market Agent to populate source health.</p>}
        </div>
      </section>
    </section>
  );
}

function CareerTransitionView({ data }) {
  const score = Number(data?.transition_score ?? data?.feasibility_score ?? 0);
  const details = data?.details || {};
  const feasibility = details.feasibility_analysis || {};
  const timeline = details.transition_timeline || {};
  const inputProfile = details.input_profile || {};
  const skillCtx = details.skill_gap_context || {};
  const skillAnalysis = skillCtx.skill_analysis || {};

  const missingCore = Array.isArray(skillAnalysis.missing_core_skills)
    ? skillAnalysis.missing_core_skills
    : (Array.isArray(data?.missing_core_skills) ? data.missing_core_skills.map((s) => ({ skill: s, priority: 'critical', category: '' })) : []);

  const missingOptional = Array.isArray(skillAnalysis.missing_optional_skills)
    ? skillAnalysis.missing_optional_skills
    : (Array.isArray(data?.missing_optional_skills) ? data.missing_optional_skills.map((s) => ({ skill: s, priority: 'medium', category: '' })) : []);

  const timelinePhases = timeline.timeline_phases || {};
  const matchedCount = Number(feasibility.matched_skills_count ?? data?.matched_skills ?? 0);
  const expectedCount = Number(data?.expected_skills ?? feasibility.skills_to_develop ?? 0);
  const partialSkills = Array.isArray(data?.partially_matched_skills) ? data.partially_matched_skills : [];

  const priorityColor = (p) => {
    if (p === 'critical') return '#FF7687';
    if (p === 'high') return '#FFB347';
    return '#0CC';
  };
  
  return (
    <section className="view-grid one-col">
      {/* Row 1: Missing Core Skills + Feasibility */}
      <section className="view-grid two-col" style={{ gap: 0, margin: 0 }}>
        <section className="panel">
          <div className="panel-head"><h3>Missing Core Skills</h3></div>
          {missingCore.length ? (
            <div className="gap-list">
              {missingCore.map((item, i) => {
                const skillName = typeof item === 'string' ? item : item.skill || item.name || String(item);
                const priority = typeof item === 'object' ? item.priority : 'critical';
                const category = typeof item === 'object' ? item.category : '';
                return (
                  <div key={i} className="gap-item" style={{ alignItems: 'flex-start', gap: 8 }}>
                    <span className="gap-number">{i + 1}</span>
                    <span className="gap-name" style={{ flex: 1 }}>{skillName}</span>
                    {category && <span className="tag" style={{ fontSize: 10, padding: '1px 6px', borderColor: 'rgba(255,255,255,0.15)', color: '#B3B3BE', textTransform: 'capitalize' }}>{category}</span>}
                    <span className="tag" style={{ fontSize: 10, padding: '1px 6px', borderColor: priorityColor(priority), color: priorityColor(priority), textTransform: 'capitalize', minWidth: 52, textAlign: 'center' }}>{priority}</span>
                  </div>
                );
              })}
            </div>
          ) : <p className="empty-text">No critical skill gaps identified.</p>}

          {missingOptional.length > 0 && (
            <>
              <div className="skill-section-title" style={{ marginTop: 16 }}>Optional / Nice-to-Have</div>
              <div className="tag-wrap">
                {missingOptional.map((item, i) => {
                  const skillName = typeof item === 'string' ? item : item.skill || item.name || String(item);
                  return <span className="tag" key={i} style={{ borderColor: '#0CC', color: '#0CC' }}>{skillName}</span>;
                })}
              </div>
            </>
          )}
        </section>

      <section className="panel">
        <div className="panel-head"><h3>Transition Feasibility</h3></div>
          <div className="skill-role-strip" style={{ marginBottom: 12 }}>
            {inputProfile.current_role && <div><span>From {" "}</span><strong>{inputProfile.current_role}</strong></div>}
            {inputProfile.target_role && <div><span>To {" "}</span><strong>{inputProfile.target_role}</strong></div>}
            <div><span>Feasibility{" "}</span><strong style={{ color: score >= 70 ? '#13a688' : score >= 40 ? '#0CC' : '#FF7687' }}>{feasibility.feasibility || (score >= 70 ? 'High' : score >= 40 ? 'Moderate' : 'Low')}</strong></div>
          </div>
        <div className="readiness-display">
          <div className="readiness-ring">
            <svg viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="40" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="8" />
              <circle cx="50" cy="50" r="40" fill="none" stroke={score >= 70 ? '#13a688' : score >= 40 ? '#0CC' : '#FF7687'} strokeWidth="8" strokeDasharray={`${score * 2.51} 251`} strokeLinecap="round" transform="rotate(-90 50 50)" />
              <text x="50" y="50" textAnchor="middle" dy="0.3em" fill="#fff" fontSize="20" fontWeight="700">{score}%</text>
            </svg>
          </div>
          <div className="readiness-info">
            <span className="readiness-category">{score >= 70 ? 'High Feasibility' : score >= 40 ? 'Moderate Feasibility' : 'Low Feasibility'}</span>
            <small>Career transition readiness</small>
          </div>
        </div>
          <div className="meta-list skill-summary-list" style={{ marginTop: 12 }}>
            <div><span>Matched Skills</span><strong>{compactNumber(matchedCount)}</strong></div>
            <div><span>Skills to Develop</span><strong>{compactNumber(feasibility.skills_to_develop ?? expectedCount)}</strong></div>
            <div><span>Est. Duration</span><strong>{timeline.estimated_months ? `${timeline.estimated_months} months` : '-'}</strong></div>
            <div><span>Est. Weeks</span><strong>{compactNumber(timeline.estimated_weeks)}</strong></div>
          </div>
          {partialSkills.length > 0 && (
            <>
              <div className="skill-section-title" style={{ marginTop: 12 }}>Partially Matched</div>
              <div className="tag-wrap">
                {partialSkills.map((s, i) => <span className="tag" key={i} style={{ borderColor: '#FFB347', color: '#FFB347' }}>{s}</span>)}
              </div>
            </>
          )}
      </section>
      </section>

      {/* Row 2: Timeline */}
      <section className="view-grid one-col" style={{ gap: 0, margin: 0 }}>
        {Object.keys(timelinePhases).length > 0 && (
      <section className="panel">
            <div className="panel-head"><h3>Learning Timeline</h3></div>
            <div className="skill-action-list">
              {Object.entries(timelinePhases).map(([phase, desc]) => (
                <div key={phase} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: '8px 0', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                  <span className="tag" style={{ textTransform: 'capitalize', minWidth: 80, textAlign: 'center', borderColor: '#13a688', color: '#13a688' }}>{phase}</span>
                  <span style={{ color: '#E8E8EE', fontSize: 13 }}>{desc}</span>
                </div>
              ))}
        </div>
            {timeline.experience_adjustment && (
              <p className="section-hint" style={{ marginTop: 8 }}>Experience adjustment: {timeline.experience_adjustment}</p>
            )}
          </section>
        )}
      </section>
    </section>
  );
}

function LearningRoadmapView({ data, userId }) {
  const roadmapSlug = String(data?.metadata?.roadmap_slug || 'generated').trim() || 'generated';
  const activeUserId = String(userId || 'demo-user').trim() || 'demo-user';
  const [skills, setSkills] = useState([]);
  const [progress, setProgress] = useState(null);
  const [selectedNodeId, setSelectedNodeId] = useState('');
  const [selectedNode, setSelectedNode] = useState(null);
  const [nodeStatus, setNodeStatus] = useState({});
  const [nodeBusy, setNodeBusy] = useState(false);
  const [promotedSkill, setPromotedSkill] = useState(null);

  const statusLabel = (status) => {
    if (status === 'completed') return 'Completed';
    if (status === 'in_progress') return 'In Progress';
    return 'Not Started';
  };

  const loadProgressAndSkills = async () => {
    if (!data) return;
    try {
      const [progressData, skillsData] = await Promise.all([
        getJson(`/roadmap/progress?roadmap_slug=${encodeURIComponent(roadmapSlug)}&user_id=${encodeURIComponent(activeUserId)}`),
        getJson(`/roadmap/skills?roadmap_slug=${encodeURIComponent(roadmapSlug)}&user_id=${encodeURIComponent(activeUserId)}`),
      ]);
      setProgress(progressData);
      const skillRows = Array.isArray(skillsData?.skills) ? skillsData.skills : [];
      setSkills(skillRows);
      const nextStatus = {};
      skillRows.forEach((skillItem) => {
        (skillItem.nodes || []).forEach((node) => {
          nextStatus[node.node_id] = node.status || 'not_started';
        });
      });
      setNodeStatus(nextStatus);
    } catch {
      setSkills([]);
      setProgress(null);
    }
  };

  useEffect(() => {
    loadProgressAndSkills();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roadmapSlug, activeUserId, !!data]);

  const openNode = async (nodeId) => {
    setSelectedNodeId(nodeId);
    try {
      const details = await getJson(`/roadmap/nodes/${encodeURIComponent(nodeId)}/resources?user_id=${encodeURIComponent(activeUserId)}`);
      setSelectedNode(details);
    } catch {
      setSelectedNode(null);
    }
  };

  const updateNodeStatus = async (status) => {
    if (!selectedNodeId) return;
    setNodeBusy(true);
    try {
      const response = await fetch(`/roadmap/nodes/${encodeURIComponent(selectedNodeId)}/status?user_id=${encodeURIComponent(activeUserId)}&roadmap_slug=${encodeURIComponent(roadmapSlug)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ status }),
      });
      if (!response.ok) {
        throw new Error('Failed to update node status');
      }
      const result = await response.json();
      setNodeStatus((prev) => ({ ...prev, [selectedNodeId]: status }));
      setSelectedNode((prev) => (prev ? { ...prev, user_status: status } : prev));
      // Show promotion banner if backend unlocked a new skill
      if (result?.promoted_skill) {
        setPromotedSkill(result.promoted_skill);
        setTimeout(() => setPromotedSkill(null), 5000);
      }
      await loadProgressAndSkills();
    } catch {
      // Status update errors are surfaced through existing top-level errors.
    } finally {
      setNodeBusy(false);
    }
  };

  if (!data) {
  return (
    <section className="view-grid one-col">
      <section className="panel">
          <p className="empty-text">No roadmap yet. Run Learning Agent to generate one.</p>
        </section>
      </section>
    );
  }

  return (
    <section className="view-grid two-col">
      {promotedSkill && (
        <div style={{
          position: 'fixed', top: 24, right: 24, zIndex: 9999,
          background: 'linear-gradient(135deg, #13a688 0%, #0a7a63 100%)',
          border: '1px solid rgba(255,255,255,0.15)',
          borderRadius: 10, padding: '14px 20px',
          boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
          display: 'flex', alignItems: 'center', gap: 12, maxWidth: 360,
        }}>
          <span style={{ fontSize: 22 }}>🎉</span>
          <div>
            <strong style={{ color: '#fff', display: 'block', fontSize: 14 }}>Skill Unlocked!</strong>
            <span style={{ color: 'rgba(255,255,255,0.85)', fontSize: 13 }}>
              <strong>{promotedSkill}</strong> has been added to your profile.
            </span>
          </div>
          <button type="button" onClick={() => setPromotedSkill(null)}
            style={{ marginLeft: 'auto', background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer', fontSize: 18, lineHeight: 1 }}>✕</button>
        </div>
      )}
      <section className="panel">
        <div className="panel-head"><h3>Roadmap Nodes</h3></div>
        <p className="section-hint">Roadmap: {roadmapSlug}</p>
        {progress ? (
          <div style={{ marginBottom: 12 }}>
            <div className="roadmap-phase-count">Completion: {progress.completion_rate}%</div>
            <div className="roadmap-phase-count">Completed {progress.completed} | In Progress {progress.in_progress} | Pending {progress.not_started}</div>
          </div>
        ) : null}
        <div className="roadmap-timeline">
          {skills.length ? skills.map((skill) => (
            <div key={skill.skill} className="roadmap-phase">
              <div className="roadmap-phase-header">
                <span className="roadmap-phase-dot" style={{ backgroundColor: '#13a688' }} />
                <h4>{skill.skill}</h4>
                <span className="roadmap-phase-count">{skill.completed}/{skill.total} complete</span>
              </div>
              <div className="roadmap-items">
                {(skill.nodes || []).map((node) => (
                  <button
                    key={node.node_id}
                    type="button"
                    className="roadmap-item"
                    onClick={() => openNode(node.node_id)}
                    style={{
                      width: '100%',
                      textAlign: 'left',
                      border: selectedNodeId === node.node_id ? '1px solid #13a688' : '1px solid transparent',
                      background: 'transparent',
                      cursor: 'pointer',
                    }}
                  >
                        <span className="roadmap-item-icon">{'->'}</span>
                    <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span>{node.title}</span>
                      <small className="section-hint" style={{ margin: 0 }}>
                        Phase: {node.phase_title || skill.skill || 'General'}
                      </small>
                    </span>
                    <span className="tag" style={{ marginLeft: 'auto' }}>{statusLabel(nodeStatus[node.node_id] || node.status || 'not_started')}</span>
                  </button>
                ))}
                      </div>
              </div>
          )) : <p className="empty-text">No nodes loaded yet.</p>}
            </div>
      </section>

      <section className="panel">
        <div className="panel-head"><h3>Node Details and Videos</h3></div>
        {!selectedNode ? (
          <p className="empty-text">Select a node to view resources and update progress.</p>
        ) : (
          <div>
            <h4 style={{ marginBottom: 8 }}>{selectedNode.title}</h4>
            <p className="section-hint">{selectedNode.phase_title || selectedNode.category || selectedNode.type}</p>
            <div className="button-row" style={{ marginBottom: 12 }}>
              {['not_started', 'in_progress', 'completed'].map((status) => (
                <button
                  key={status}
                  type="button"
                  disabled={nodeBusy}
                  onClick={() => updateNodeStatus(status)}
                >
                  {statusLabel(status)}
                </button>
          ))}
        </div>
            <div className="video-cards-list">
              {(selectedNode?.resources?.videos || []).length
                ? selectedNode.resources.videos.map((video, index) => {
                  const isSearchLink = video.is_search_link === true;
                  // Prefer backend thumbnail from format_videos(), fallback to derived URL.
                  const videoId =
                    video.video_id ||
                    (!isSearchLink && video.youtube_url?.match(
                      /(?:v=|youtu\.be\/|embed\/)([A-Za-z0-9_-]{11})/
                    )?.[1]) ||
                    null;

                  const thumbnailUrl =
                    video.thumbnail ||
                    (videoId ? `https://img.youtube.com/vi/${videoId}/hqdefault.jpg` : null);
                  const videoUrl =
                    video.youtube_url ||
                    (videoId ? `https://www.youtube.com/watch?v=${videoId}` : '#');

                  return (
                    <a
                      key={videoUrl + index}
                      href={videoUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="video-card-link"
                      style={{ textDecoration: 'none', color: 'inherit' }}
                    >
                      <div className="video-card-item" style={isSearchLink ? { borderColor: 'rgba(19,166,136,0.4)', background: 'rgba(19,166,136,0.06)' } : {}}>
                        {/* Thumbnail */}
                        <div className="video-thumb-wrap">
                          {thumbnailUrl ? (
                            <img
                              src={thumbnailUrl}
                              alt={video.title || 'Video thumbnail'}
                              className="video-thumb"
                              onError={(e) => {
                                // Fallback to default thumbnail if hqdefault or custom URL fails.
                                e.target.src = `https://img.youtube.com/vi/${videoId}/default.jpg`;
                                // If that also fails, show placeholder
                                e.target.onerror = () => {
                                  e.target.style.display = 'none';
                                };
                              }}
                            />
                          ) : (
                            <div className="video-thumb-placeholder" style={isSearchLink ? { fontSize: 22 } : {}}>
                              {isSearchLink ? '🔍' : '▶'}
                            </div>
                          )}
                          {!isSearchLink && <div className="video-play-overlay">▶</div>}
                        </div>

                        {/* Info */}
                        <div className="video-card-info">
                          <span className="video-card-index" style={isSearchLink ? { color: '#13a688' } : {}}>
                            {isSearchLink ? 'YouTube' : `#${index + 1}`}
                          </span>
                          <span className="video-card-title">
                            {isSearchLink
                              ? (video.title || 'Search on YouTube').replace('Search: ', '')
                              : (video.title || 'Untitled Video')}
                          </span>
                          {video.channel && (
                            <span className="video-card-channel">{video.channel}</span>
                          )}
                          {video.duration && (
                            <span className="video-card-duration">{video.duration}</span>
                          )}
                        </div>
                      </div>
                    </a>
                  );
                })
                : <p className="empty-text">No videos mapped for this node yet.</p>}
            </div>
          </div>
        )}
      </section>
    </section>
  );
}

function TalentMatchesView({ data }) {
  const matches = Array.isArray(data?.matches) ? data.matches : [];
  
  return (
    <section className="view-grid two-col">
      <section className="panel">
        <div className="panel-head"><h3>Talent Matches</h3></div>
        <div className="match-grid">
          {matches.length
            ? matches.slice(0, 10).map((match, i) => (
                <div key={i} className="match-card">
                  {(() => {
                    const missingSkills = deriveMissingSkills(match);
                    return (
                      <>
                  <div className="match-card-header">
                    <span className="match-rank">#{i + 1}</span>
                    <strong>{match.name || match.candidate_name || `Candidate ${i + 1}`}</strong>
                  </div>
                  <div className="match-score-bar">
                    <div className="match-score-fill" style={{ width: `${deriveMatchPercentValue(match)}%` }} />
                    <span>{deriveMatchScore(match)}</span>
                  </div>
                  {match.role && <div className="match-role">{match.role}</div>}
                  <div className="match-skill-block">
                    <span className="match-skill-label">Missing Skills</span>
                    <div className="tag-wrap">
                      {missingSkills.length
                        ? missingSkills.map((skill, skillIndex) => (
                            <span key={`${skill}-${skillIndex}`} className="tag tag-gap">{skill}</span>
                          ))
                        : <span className="tag tag-muted">No missing skills</span>}
                    </div>
                  </div>
                      </>
                    );
                  })()}
                </div>
              ))
            : <p className="empty-text">No matches yet. Run Talent Matching or Manager Workflow to find candidates.</p>}
        </div>
      </section>
    </section>
  );
}

function UserProfileView({ user }) {
  const [profileData, setProfileData] = useState(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileError, setProfileError] = useState('');

  useEffect(() => {
    async function fetchProfile() {
      setProfileLoading(true);
      setProfileError('');
      try {
        const data = await getJson('/api/user/profile');
        console.log('FULL PROFILE DATA:', JSON.stringify(data, null, 2))
        setProfileData(data);
        
      } catch {
        setProfileError('Failed to load profile data. Please try again.');
      } finally {
        setProfileLoading(false);
      }
    }
    fetchProfile();
  }, []);

  // ── Flatten ALL skills from every possible location ──
  const extractSkills = (data) => {
  if (!data) return [];

  const found = new Set();

  const addAll = (arr) => (arr || []).forEach(s => {
    if (typeof s === 'string') found.add(s);
    if (typeof s === 'object' && s?.name) found.add(s.name);
  });

  // ✅ THE FIX — skills live under data.profile.skills
  addAll(data?.profile?.skills);

  // Fallbacks just in case
  addAll(data.skills);
  addAll(data.technical_skills);
  addAll(data.soft_skills);

  // One level deep on all nested objects
  Object.values(data).forEach(val => {
    if (val && typeof val === 'object' && !Array.isArray(val)) {
      addAll(val.skills);
      addAll(val.technical_skills);
      addAll(val.soft_skills);
    }
  });

  return [...found].filter(Boolean);
};

  // ── Build categories ──
  const buildSkillCategories = (skills = []) => {
    const categories = {
      'Cloud & DevOps': skills.filter(s =>
        /aws|azure|gcp|docker|kubernetes|k8s|jenkins|ci\/cd|ci|cd|cloud|devops|terraform|ansible/i.test(s)
      ),
      'Languages': skills.filter(s =>
        /\bjava\b|python|javascript|typescript|\bgo\b|rust|c\+\+|c#|ruby|php|swift|kotlin|scala/i.test(s)
      ),
      'Frameworks': skills.filter(s =>
        /spring|react|angular|vue|django|flask|express|node|next|nuxt|redux|bootstrap|tailwind|material.?ui/i.test(s)
      ),
      'Databases': skills.filter(s =>
        /sql|postgresql|mysql|mongodb|redis|elastic|kafka|database|cassandra|dynamo/i.test(s)
      ),
      'Tools': skills.filter(s =>
        /git|github|gitlab|bitbucket|jira|confluence|linux|unix|figma|jest|webpack|vite|postman/i.test(s)
      ),
      'Methodologies': skills.filter(s =>
        /agile|kanban|scrum|collaboration|communication|user.centered|ux|design|wcag|accessibility|rest|performance/i.test(s)
      ),
    };

    const categorized = new Set(Object.values(categories).flat());
    const other = skills.filter(s => !categorized.has(s));
    if (other.length) categories['Technologies'] = other;

    return Object.entries(categories).filter(([, items]) => items.length > 0);
  };

  // ── Extract roadmap node titles only ──
const extractNodeTitles = (data) => {
  // ✅ nodes live under data.roadmap.nodes
  const nodes = data?.roadmap?.nodes || [];
  return nodes.map(n => ({
    title:  n.title  || n.name || '',
    status: n.status || 'not_started',
  })).filter(n => n.title);
};

  const getStatusIcon = (status) => {
    if (status === 'completed')   return '✅';
    if (status === 'in_progress') return '🔄';
    return '⬜'; // not_started / pending
  };

  const getStatusColor = (status) => {
    if (status === 'completed')   return '#13a688';
    if (status === 'in_progress') return '#00CCCC';
    return '#B3B3BE'; // not_started / pending
  };

  // ── Loading ──
  if (profileLoading) {
    return (
      <section className="view-grid one-col">
        <section className="panel">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '24px 0', color: '#B3B3BE' }}>
            <div className="pd-spinner" />
            <span>Loading your profile data...</span>
          </div>
        </section>
      </section>
    );
  }

  // ── Error ──
  if (profileError) {
    return (
      <section className="view-grid one-col">
        <section className="panel">
          <p style={{ color: '#FF7687', padding: '12px 0' }}>{profileError}</p>
        </section>
      </section>
    );
  }
  const profileUser  = profileData?.profile  || {};
  const roadmapData  = profileData?.roadmap  || {};
  const skills       = extractSkills(profileData);
  const skillGroups  = buildSkillCategories(skills);
const roadmapNodes = extractNodeTitles(profileData);

const total     = roadmapData.total        || 0;
const completed = roadmapData.completed    || 0;
const inProg    = roadmapData.in_progress  || 0;
const pending   = roadmapData.not_started  || 0;
const pct       = roadmapData.completion_rate
                    ? Math.round(roadmapData.completion_rate)
                    : 0;

  return (
    <section className="view-grid one-col">

      {/* ══════════════════════════════════════
          ROW 1 — User Info Card (no header)
          ══════════════════════════════════════ */}
      <section className="panel">
        <div className="profile-card">
          <div className="profile-avatar">
            {(user?.name || user?.email || 'U').charAt(0).toUpperCase()}
          </div>
          <div className="profile-details">
            <h4>{user?.name || 'Unknown'}</h4>
            <p>{user?.role || 'Role not set'}</p>
            <span className="profile-exp">
              {user?.department || 'Department not set'}
            </span>
          </div>
        </div>

        <div style={{ marginTop: '14px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {user?.email && (
            <div className="profile-meta">
              <span>Email</span>
              <strong>{user.email}</strong>
            </div>
          )}
          {user?.department && (
            <div className="profile-meta">
              <span>Department</span>
              <strong>{user.department}</strong>
            </div>
          )}
          {user?.role && (
            <div className="profile-meta">
              <span>Role</span>
              <strong>{user.role}</strong>
            </div>
          )}
          {profileData?.roadmap?.roadmap_slug && (
            <div className="profile-meta">
              <span>Roadmap</span>
              <strong>{profileData.roadmap.roadmap_slug}</strong>
            </div>
          )}
        </div>
      </section>

      {/* ══════════════════════════════════════
          ROW 2 — Skills (no header)
          ══════════════════════════════════════ */}
      <section className="view-grid two-col">

        {/* Left — ring + meters */}
        <section className="panel">

          {/* Ring — only show if skills exist */}
          {skills.length > 0 && (
            <div className="readiness-display">
              <div className="readiness-ring">
                <svg viewBox="0 0 100 100">
                  <circle
                    cx="50" cy="50" r="40"
                    fill="none"
                    stroke="rgba(255,255,255,0.08)"
                    strokeWidth="8"
                  />
                  <circle
                    cx="50" cy="50" r="40"
                    fill="none"
                    stroke="#00CCCC"
                    strokeWidth="8"
                    strokeDasharray={`${Math.min(skills.length * 2, 251)} 251`}
                    strokeLinecap="round"
                    transform="rotate(-90 50 50)"
                  />
                  <text
                    x="50" y="46"
                    textAnchor="middle"
                    fill="#fff"
                    fontSize="18"
                    fontWeight="700"
                  >
                    {skills.length}
                  </text>
                  <text
                    x="50" y="60"
                    textAnchor="middle"
                    fill="#B3B3BE"
                    fontSize="9"
                  >
                    skills
                  </text>
                </svg>
              </div>
              <div className="readiness-info">
                <span className="readiness-category">Skills Indexed</span>
                <small>{skillGroups.length} categories detected</small>
              </div>
            </div>
          )}

          {/* Meters per category */}
          {skillGroups.length > 0 && (
            <div className="skill-meters">
              {skillGroups.map(([category, items]) => (
                <div className="meter" key={category}>
                  <span>{category}</span>
                  <div className="meter-bar">
                    <div
                      className="meter-fill meter-success"
                      style={{
                        width: `${(items.length / skills.length) * 100}%`,
                      }}
                    />
                  </div>
                  <strong>{items.length}</strong>
                </div>
              ))}
            </div>
          )}

          {skills.length === 0 && (
            <p className="empty-text">
              No skills found. Run Resume Analysis to populate your profile.
            </p>
          )}
        </section>

        {/* Right — categorised skill tags (no header) */}
        <section className="panel">

          {skills.length > 0 && (
            <div className="skill-count-badge">{skills.length} skills found</div>
          )}

          {skillGroups.length > 0 ? (
            <div className="skill-categories">
              {skillGroups.map(([category, items]) => (
                <div key={category} className="skill-category">
                  <h4 className="skill-category-title">{category}</h4>
                  <div className="tag-wrap">
                    {items.map((skill, i) => (
                      <span className="tag" key={`${category}-${i}`}>
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="empty-text">
              No skills found. Run Resume Analysis to populate your profile.
            </p>
          )}
        </section>
      </section>

      {/* ══════════════════════════════════════
          ROW 3 — Roadmap Progress (no header, no nodes panel)
          ══════════════════════════════════════ */}
      <section className="view-grid two-col">

        {/* Left — progress ring + meters */}
        <section className="panel">

          {total > 0 ? (
            <>
              <div className="readiness-display">
                <div className="readiness-ring">
                  <svg viewBox="0 0 100 100">
                    <circle
                      cx="50" cy="50" r="40"
                      fill="none"
                      stroke="rgba(255,255,255,0.08)"
                      strokeWidth="8"
                    />
                    <circle
                      cx="50" cy="50" r="40"
                      fill="none"
                      stroke={pct >= 70 ? '#13a688' : pct >= 40 ? '#00CCCC' : '#FF7687'}
                      strokeWidth="8"
                      strokeDasharray={`${pct * 2.51} 251`}
                      strokeLinecap="round"
                      transform="rotate(-90 50 50)"
                    />
                    <text
                      x="50" y="46"
                      textAnchor="middle"
                      fill="#fff"
                      fontSize="18"
                      fontWeight="700"
                    >
                      {pct}%
                    </text>
                    <text
                      x="50" y="60"
                      textAnchor="middle"
                      fill="#B3B3BE"
                      fontSize="9"
                    >
                      complete
                    </text>
                  </svg>
                </div>
                <div className="readiness-info">
                  <span className="readiness-category">
                    {pct >= 70 ? 'On Track' : pct >= 40 ? 'In Progress' : 'Just Started'}
                  </span>
                  <small>{completed} of {total} topics done</small>
                </div>
              </div>

              <div className="skill-meters">
                <div className="meter">
                  <span>Completed</span>
                  <div className="meter-bar">
                    <div
                      className="meter-fill meter-success"
                      style={{ width: `${(completed / total) * 100}%` }}
                    />
                  </div>
                  <strong>{completed}</strong>
                </div>
                <div className="meter">
                  <span>In Progress</span>
                  <div className="meter-bar">
                    <div
                      className="meter-fill"
                      style={{
                        width: `${(inProg / total) * 100}%`,
                        background: '#00CCCC',
                      }}
                    />
                  </div>
                  <strong>{inProg}</strong>
                </div>
                <div className="meter">
                  <span>Pending</span>
                  <div className="meter-bar">
                    <div
                      className="meter-fill meter-danger"
                      style={{ width: `${(pending / total) * 100}%` }}
                    />
                  </div>
                  <strong>{pending}</strong>
                </div>
              </div>
            </>
          ) : (
            <p className="empty-text">
              No roadmap data yet. Run Learning Agent to generate one.
            </p>
          )}
        </section>

        {/* Right — topic name tags only (no node_type, no phases) */}
        <section className="panel">

          {roadmapNodes.length > 0 ? (
            <>
              <div className="skill-count-badge">
                {roadmapNodes.length} topics in your roadmap
              </div>
              <div className="tag-wrap" style={{ marginTop: '12px' }}>
                {roadmapNodes.map((node, i) => (
                  <span
                    className="tag"
                    key={i}
                    style={{
                      borderColor: getStatusColor(node.status),
                      color: getStatusColor(node.status),
                    }}
                  >
                    {getStatusIcon(node.status)} {node.title}
                  </span>
                ))}
              </div>
            </>
          ) : (
            <p className="empty-text">
              No roadmap topics yet. Run Learning Agent to generate one.
            </p>
          )}
        </section>
      </section>

    </section>
  );
}

export default function App() {
  const [view, setView] = useState(readInitialView());
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [currentUser, setCurrentUser] = useState(null);
  const [needsProfile, setNeedsProfile] = useState(false);


  useEffect(() => {
    async function checkAuth() {
      try {
        const data = await getJson('/api/auth/me');
        if (data?.user) {
          const profile = data.user;

        // ✅ Check if this is a DIFFERENT user than what's cached
        const cachedUser = sessionStorage.getItem('siemens_user');
        const cachedEmail = cachedUser ? JSON.parse(cachedUser)?.email : null;

        if (cachedEmail && cachedEmail !== profile.email) {
          // ✅ Different user detected — clear all stale data
          setResumeData(null);
          setSkillData(null);
          setMarketData(null);
          setCareerData(null);
          setRoadmapData(null);
          setTalentData(null);
          setEmployeeWorkflowData(null);
          setManagerWorkflowData(null);
          setPipelineData(null);
          setResumeText('');
          setTargetRole('');
          setJobDescription('');
          setConfirmedRole('');
        }

          setCurrentUser(profile);
          setIsAuthenticated(true);
          const incomplete = !profile.name || !profile.role;
          setNeedsProfile(incomplete);
          sessionStorage.setItem('siemens_auth', 'true');
          sessionStorage.setItem('siemens_user', JSON.stringify(profile));
          sessionStorage.setItem('siemens_needs_profile', incomplete ? 'true' : 'false');

          if (incomplete) {
            window.location.hash = '#profile-creation';
          }
        } else {
          window.location.href = '/';
        }
      } catch {
        window.location.href = '/';
      }
    }
    checkAuth();
  }, []);

  const [resumeText, setResumeText] = useState('');
  const [resumeFile, setResumeFile] = useState(null);
  const [targetRole, setTargetRole] = useState('');
  const [jobDescription, setJobDescription] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  const [showRoleDialog, setShowRoleDialog] = useState(false);
  const [roleSuggestions, setRoleSuggestions] = useState([]);
  const [showRoleConfirm, setShowRoleConfirm] = useState(false);
  const [confirmedRole, setConfirmedRole] = useState('');

  const [health, setHealth] = useState(null);
  const [frameworks, setFrameworks] = useState(null);

  const [resumeData, setResumeData] = useState(null);
  const [skillData, setSkillData] = useState(null);
  const [marketData, setMarketData] = useState(null);
  const [careerData, setCareerData] = useState(null);
  const [roadmapData, setRoadmapData] = useState(null);
  const [talentData, setTalentData] = useState(null);
  const [employeeWorkflowData, setEmployeeWorkflowData] = useState(null);
  const [managerWorkflowData, setManagerWorkflowData] = useState(null);
  const [pipelineData, setPipelineData] = useState(null);

  const [activeStage, setActiveStage] = useState('');
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  // ✅ Safety net — clears all data whenever the logged-in user changes
const prevUserEmailRef = useRef(null);

useEffect(() => {
  if (!currentUser?.email) return;

  // If user email changed (new login), wipe everything
  if (prevUserEmailRef.current && prevUserEmailRef.current !== currentUser.email) {
    setResumeData(null);
    setSkillData(null);
    setMarketData(null);
    setCareerData(null);
    setRoadmapData(null);
    setTalentData(null);
    setEmployeeWorkflowData(null);
    setManagerWorkflowData(null);
    setPipelineData(null);
    setResumeText('');
    setTargetRole('');
    setJobDescription('');
    setConfirmedRole('');
    console.log(`[AUTH] User switched: ${prevUserEmailRef.current} → ${currentUser.email} — state cleared`);
  }

  prevUserEmailRef.current = currentUser.email;
}, [currentUser?.email]);

  const handleSiemensLogin = async (credentials) => {
    // ✅ Step 1 — Wipe previous user session
    sessionStorage.removeItem('siemens_auth');
    sessionStorage.removeItem('siemens_user');
    sessionStorage.removeItem('siemens_token');
    sessionStorage.removeItem('siemens_needs_profile');

    // ✅ Step 2 — Clear ALL previous user's data before login
    setResumeData(null);
    setSkillData(null);
    setMarketData(null);
    setCareerData(null);
    setRoadmapData(null);
    setTalentData(null);
    setEmployeeWorkflowData(null);
    setManagerWorkflowData(null);
    setPipelineData(null);
    setResumeText('');
    setTargetRole('');
    setJobDescription('');
    setConfirmedRole('');

    // ✅ Step 3 — Now login
    const data = await postJson('/api/auth/login', credentials);
    sessionStorage.setItem('siemens_auth', 'true');
    sessionStorage.setItem('siemens_user', JSON.stringify(data.user));
    sessionStorage.setItem('siemens_token', data.token);
    const profile = data.user;
    const incomplete = !profile.name || !profile.role;
    sessionStorage.setItem('siemens_needs_profile', incomplete ? 'true' : 'false');
    setCurrentUser(profile);
    setIsAuthenticated(true);
    setNeedsProfile(incomplete);
  };

  const handleProfileComplete = (profile) => {
    sessionStorage.setItem('siemens_user', JSON.stringify(profile));
    sessionStorage.setItem('siemens_needs_profile', 'false');
    setCurrentUser(profile);
    setNeedsProfile(false);
  };

  const handleLogout = async () => {
    try {
      await postJson('/api/auth/logout', {});
    } catch {
      // ignore logout errors
    }
    sessionStorage.removeItem('siemens_auth');
    sessionStorage.removeItem('siemens_user');
    sessionStorage.removeItem('siemens_token');
    sessionStorage.removeItem('siemens_needs_profile');
    setIsAuthenticated(false);
    setCurrentUser(null);
    setNeedsProfile(false);
    setResumeData(null);
    setSkillData(null);
    setMarketData(null);
    setCareerData(null);
    setRoadmapData(null);
    setTalentData(null);
    setEmployeeWorkflowData(null);
    setManagerWorkflowData(null);
    setPipelineData(null);
  };

  async function refreshSkillSummaryFromProfile(profileSource, selectedTargetRole) {
    const liveSkills = sanitizeSkillList(profileSource?.skills || profileSource?.current_skills || []);
    // The role is driven entirely by the user-provided target role (the box), never the
    // detected role from the resume.
    const targetRoleValue = String(selectedTargetRole || '').trim();
    const currentRoleValue = String(profileSource?.role || profileSource?.current_role || targetRoleValue || '').trim();
    // Use the same experience the manual "Run Skill Agent" path sends, otherwise the
    // experience bucket defaults to junior here and the readiness score computed during
    // auto-hydration differs from the one shown after running the agent manually.
    const experienceYears = Number(profileSource?.experience_years ?? profileSource?.experience ?? 0) || 0;

    if (!liveSkills.length || !targetRoleValue) {
      return null;
    }

    const skillGapData = await postJson('/analyze/skill-gaps', {
      skills: liveSkills,
      role: targetRoleValue,
      current_role: currentRoleValue,
      target_role: targetRoleValue,
      experience_years: experienceYears,
    });
    setSkillData(skillGapData);

    // Hydrate the remaining overview metrics (market gaps, transition, roadmap) so the
    // KPI dashboard reflects a complete analysis instead of partial data. Each call is
    // best-effort: a failure in one analysis must not break the others.
    const skillGapContext = skillGapData?.skill_gap_json || null;
    const transitionPayload = {
      profile: { skills: liveSkills, role: currentRoleValue || targetRoleValue },
      target_role: targetRoleValue,
    };
    if (skillGapContext) {
      transitionPayload.skill_gap_context = {
        source_agent: 'skill_agent',
        readiness_summary: skillGapContext.readiness_summary,
        core_gaps: skillGapContext.core_gaps,
        skill_analysis: skillGapContext.skill_analysis,
      };
    }

    const [marketOutcome, careerOutcome] = await Promise.allSettled([
      postJson('/analyze/market-gaps', { skills: liveSkills, role: targetRoleValue }),
      postJson('/analyze/transition', transitionPayload),
    ]);

    let marketResult = null;
    if (marketOutcome.status === 'fulfilled') {
      marketResult = marketOutcome.value;
      setMarketData(marketResult);
    } else {
      logger.warn('Market hydration failed: %s', marketOutcome.reason);
    }

    if (careerOutcome.status === 'fulfilled') {
      setCareerData(careerOutcome.value);
    } else {
      logger.warn('Transition hydration failed: %s', careerOutcome.reason);
    }

    try {
      const coreGaps = Array.isArray(skillGapData?.core_gaps) ? skillGapData.core_gaps : [];
      const marketGaps = Array.isArray(marketResult?.market_gaps) ? marketResult.market_gaps : [];
      const combinedGaps = Array.from(
        new Set([...coreGaps, ...marketGaps].map((gap) => String(gap || '').trim()).filter(Boolean)),
      );
      const roadmapResult = await postJson('/generate/roadmap', {
        profile: { skills: liveSkills, role: targetRoleValue },
        gaps: combinedGaps,
        target_role: targetRoleValue,
      });
      setRoadmapData(roadmapResult);
    } catch (error) {
      logger.warn('Roadmap hydration failed: %s', error);
    }

    return skillGapData;
  }

  const profile = useMemo(() => {
    if (resumeData?.profile) return resumeData.profile;
    if (employeeWorkflowData?.analysis?.profile) return employeeWorkflowData.analysis.profile;
    if (pipelineData?.analysis?.profile) return pipelineData.analysis.profile;
    return {};
  }, [employeeWorkflowData, pipelineData, resumeData]);

  const skills = useMemo(() => sanitizeSkillList(profile?.skills || profile?.current_skills || []), [profile]);
  const currentRole = useMemo(() => profile?.role || profile?.current_role || '', [profile]);
  const allGaps = useMemo(() => mergeGaps(skillData, marketData), [skillData, marketData]);

  const metrics = useMemo(() => {
    const employeeAnalysis = extractWorkflowAnalysis(employeeWorkflowData);
    const pipelineAnalysis = extractWorkflowAnalysis(pipelineData);
    const activeAnalysis = Object.keys(employeeAnalysis).length ? employeeAnalysis : pipelineAnalysis;
    const skillAnalysis = skillData?.skill_gap_json || skillData?.details || activeAnalysis?.skill_analysis || {};
    const careerAnalysis = careerData?.details || activeAnalysis?.career_analysis || {};
    const roadmapSource = roadmapData || activeAnalysis?.roadmap || activeAnalysis?.learning_roadmap || pipelineAnalysis?.learning_roadmap;
    const roadmapPayload = normalizeRoadmapPayload(roadmapSource);
    const matchSource = talentData?.matches || managerWorkflowData?.matches || pipelineAnalysis?.matches || null;

    const knownSkillsCount = Number(
      skillAnalysis?.readiness_summary?.skills_completed ??
      (Array.isArray(skillAnalysis?.skill_analysis?.matched_skills) ? skillAnalysis.skill_analysis.matched_skills.length : 0),
    );

    const requiredSkillsCount = Number(
      skillAnalysis?.readiness_summary?.total_skills_required ??
      skillData?.expected_skills_count ??
      (Array.isArray(skillAnalysis?.skill_analysis?.matched_skills)
        ? skillAnalysis.skill_analysis.matched_skills.length + Number(skillAnalysis?.readiness_summary?.skills_missing ?? 0)
        : 0),
    );

    const readinessScore =
      requiredSkillsCount > 0
        ? Number(((knownSkillsCount / requiredSkillsCount) * 100).toFixed(2))
        : (skillData?.readiness_score ??
          skillAnalysis?.readiness_summary?.readiness_score ??
          activeAnalysis?.readiness_score ??
          '-');

    const transitionScore =
      careerData?.transition_score ??
      careerAnalysis?.feasibility_analysis?.transition_score ??
      activeAnalysis?.transition_score ??
      '-';

    const coreGapCount =
      (Array.isArray(skillData?.core_gaps) && skillData.core_gaps.length) ||
      (Array.isArray(skillAnalysis?.core_gaps) && skillAnalysis.core_gaps.length) ||
      (Array.isArray(activeAnalysis?.core_gaps) && activeAnalysis.core_gaps.length) ||
      (Array.isArray(skillAnalysis?.skill_analysis?.skill_gaps) && skillAnalysis.skill_analysis.skill_gaps.length) ||
      '-';

    const marketGapCount =
      (Array.isArray(marketData?.market_gaps) && marketData.market_gaps.length) ||
      (Array.isArray(activeAnalysis?.market_gaps) && activeAnalysis.market_gaps.length) ||
      (Array.isArray(activeAnalysis?.market_analysis?.market_gaps) && activeAnalysis.market_analysis.market_gaps.length) ||
      '-';

    const roadmapProjectCount =
      (Array.isArray(roadmapData?.projects?.details) && roadmapData.projects.details.length) ||
      (Array.isArray(roadmapPayload?.projects?.details) && roadmapPayload.projects.details.length) ||
      (Array.isArray(activeAnalysis?.learning_roadmap?.project_roadmap?.projects) && activeAnalysis.learning_roadmap.project_roadmap.projects.length) ||
      '-';

    const matchCount = Array.isArray(matchSource) ? matchSource.length : '-';

    return {
      readiness: compactNumber(readinessScore),
      transition: compactNumber(transitionScore),
      coreGaps: compactNumber(coreGapCount),
      marketGaps: compactNumber(marketGapCount),
      roadmapProjects: compactNumber(roadmapProjectCount),
      matches: compactNumber(matchCount),
    };
  }, [careerData, employeeWorkflowData, managerWorkflowData, marketData, pipelineData, roadmapData, skillData, talentData]);

  const backendStack = useMemo(() => (Array.isArray(frameworks?.backend) ? frameworks.backend.join(' | ') : '-'), [frameworks]);

  useEffect(() => {
    const onHashChange = () => setView(readInitialView());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    if (!window.location.hash) setViewHash('overview');
  }, []);

  useEffect(() => {
    async function bootstrap() {
      try {
        const [healthData, frameworkData] = await Promise.all([
          getJson('/health'),
          getJson('/meta/frameworks'),
        ]);
        setHealth(healthData);
        setFrameworks(frameworkData);
      } catch {
        // Keep UI usable when backend is unavailable on first load.
      }
    }
    bootstrap();
  }, []);



  if (!isAuthenticated) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#000028', gap: '16px' }}>
        <p style={{ color: '#0CC', fontSize: '18px', fontWeight: '600' }}>Checking authentication...</p>
        <p style={{ color: '#B3B3BE', fontSize: '13px' }}>If this persists, open browser console (F12) and check for errors</p>
      </div>
    );
  }

  if (needsProfile) {
    return <ProfileCreationScreen initialUser={currentUser} onComplete={handleProfileComplete} />;
  }

  function fail(error) {
    setErrorMessage(parseError(error));
    setSuccessMessage('');
  }

  function clearError() {
    setErrorMessage('');
  }

  function showSuccess(msg) {
    setSuccessMessage(msg);
    setTimeout(() => setSuccessMessage(''), 3000);
  }

  async function guarded(stage, action) {
    setBusy(true);
    setActiveStage(stage);
    clearError();
    try {
      await action();
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
      setActiveStage('');
    }
  }

  async function refreshHealthAndMeta() {
    await guarded('health', async () => {
      const [healthData, frameworkData] = await Promise.all([
        getJson('/health'),
        getJson('/meta/frameworks'),
      ]);
      setHealth(healthData);
      setFrameworks(frameworkData);
    });
  }

  async function analyzeResumeText() {
    const text = resumeText.trim();
    if (!text) {
      setErrorMessage('Resume text is required.');
      return;
    }
    await guarded('resume', async () => {
      const data = await postJson('/analyze/resume', { text });
      setResumeData(data);

      const manualRole = targetRole.trim();
      // The target role is set manually by the user (via the box or the confirmation
      // dialog) — never auto-filled from the detected role. Only prompt for a role
      // when the box is still empty.
      if (!manualRole && data?.needs_role_confirmation && data?.role_suggestions?.length > 0) {
        setRoleSuggestions(data.role_suggestions);
        setShowRoleDialog(true);
      } else {
        try {
          await refreshSkillSummaryFromProfile(data?.profile, manualRole);
        } catch (error) {
          logger.warn('Skill summary hydration after resume analysis failed: %s', error);
        }
        showSuccess('Resume text analyzed successfully!');
        setView('resume-output');
        setViewHash('resume-output');
      }
    });
  }

  async function analyzeResumeFile() {
    if (!resumeFile) {
      setErrorMessage('Upload a resume file first.');
      return;
    }
    await guarded('resume', async () => {
      const form = new FormData();
      form.append('file', resumeFile);
      const response = await fetch('/analyze/resume/file', { method: 'POST', body: form });
      if (!response.ok) {
        const raw = await response.text();
        let message = raw;
        try {
          const payload = JSON.parse(raw);
          message = payload?.detail || payload?.message || raw;
        } catch {
          // Keep plain-text response message when body is not JSON.
        }
        throw new Error(message || `Request failed: ${response.status}`);
      }
      const data = await response.json();
      
      // Check if role confirmation is needed BEFORE navigating
      const manualRole = targetRole.trim();
      // The target role is set manually by the user (via the box or the confirmation
      // dialog) — never auto-filled from the detected role. Only prompt for a role
      // when the box is still empty.
      if (!manualRole && data?.needs_role_confirmation && data?.role_suggestions?.length > 0) {
        setRoleSuggestions(data.role_suggestions);
        setResumeData(data);
        setShowRoleDialog(true);
        // Don't navigate - let the modal handle it after selection
      } else {
        setResumeData(data);
        try {
          await refreshSkillSummaryFromProfile(data?.profile, manualRole);
        } catch (error) {
          logger.warn('Skill summary hydration after resume file analysis failed: %s', error);
        }
        showSuccess('Resume file analyzed successfully!');
        setView('resume-output');
        setViewHash('resume-output');
      }
    });
  }

  async function handleRoleSelect(selectedRole) {
    setTargetRole(selectedRole);
    setShowRoleDialog(false);
    try {
      await refreshSkillSummaryFromProfile(resumeData?.profile, selectedRole);
    } catch (error) {
      logger.warn('Skill summary hydration after role confirmation failed: %s', error);
    }
    showSuccess('Role confirmed! Resume analyzed successfully.');
    setView('resume-output');
    setViewHash('resume-output');
  }

async function analyzeSkillGap() {
     const selectedTargetRole = targetRole.trim() || currentRole;
     if (!skills.length || !selectedTargetRole) {
       setErrorMessage('Run resume analysis first so role and skills are available.');
       return;
     }
     await guarded('skill', async () => {
       const data = await postJson('/analyze/skill-gaps', {
         skills,
         role: currentRole || selectedTargetRole,
         current_role: currentRole || selectedTargetRole,
         target_role: selectedTargetRole,
         experience_years: profile?.experience_years || profile?.experience || 0,
       });
       setSkillData(data);
       showSuccess('Skill analysis completed successfully.');
       setView('skill-output');
       setViewHash('skill-output');
     });
   }

async function analyzeMarket() {
     const selectedTargetRole = targetRole.trim() || currentRole;
     if (!skills.length || !selectedTargetRole) {
       setErrorMessage('Run resume analysis first so skills are available.');
       return;
     }
     await guarded('market', async () => {
       const data = await postJson('/analyze/market-gaps', {
         skills,
         role: selectedTargetRole,
       });
       setMarketData(data);
       setView('market-output');
       setViewHash('market-output');
     });
   }

async function analyzeCareer() {
    const selectedTargetRole = targetRole.trim();
    const effectiveCurrentRole = confirmedRole || currentRole;
    if (!skills.length || !effectiveCurrentRole || !selectedTargetRole) {
       setErrorMessage('Resume profile and target role are required for transition analysis.');
       return;
     }
     await guarded('career', async () => {
       const skillGapContext = skillData?.skill_gap_json || null;
       const payload = {
        profile: { skills, role: currentRole },
         target_role: selectedTargetRole,
       };
       if (skillGapContext) {
         payload.skill_gap_context = {
           source_agent: 'skill_agent',
           readiness_summary: skillGapContext.readiness_summary,
           core_gaps: skillGapContext.core_gaps,
           skill_analysis: skillGapContext.skill_analysis,
         };
       }
       const data = await postJson('/analyze/transition', payload);
       setCareerData(data);
       setView('career-output');
       setViewHash('career-output');
     });
   }

async function generateRoadmap() {
    const selectedTargetRole = targetRole.trim() || confirmedRole || currentRole;
     if (!skills.length || !selectedTargetRole) {
       setErrorMessage('Role, skills, and target role are required before roadmap generation.');
       return;
     }

     await guarded('learning', async () => {
      const skillGapPayload = skillData?.skill_gap_json || skillData?.details || {};
       const data = await postJson('/generate/roadmap', {
        skill_gap: Object.keys(skillGapPayload || {}).length
          ? skillGapPayload
          : {
            core_gaps: allGaps,
            profile: { skills, role: currentRole || selectedTargetRole },
          },
         target_role: selectedTargetRole,
       });
       setRoadmapData(data);
       setView('roadmap-output');
       setViewHash('roadmap-output');
     });
   }

  async function matchTalent() {
    const jd = jobDescription.trim();
    if (!jd) {
      setErrorMessage('Job description is required for talent matching.');
      return;
    }
    await guarded('talent', async () => {
      const data = await postJson('/talent/match', { job_description: jd });
      setTalentData(data);
      setView('talent-output');
      setViewHash('talent-output');
    });
  }

async function runEmployeeWorkflow() {
     const text = resumeText.trim();
     const selectedTargetRole = targetRole.trim() || currentRole;
     if (!text) {
       setErrorMessage('Resume text is required for employee workflow.');
       return;
     }
     await guarded('workflow', async () => {
       const data = await postJson('/workflow/employee', {
         resume_text: text,
         target_role: selectedTargetRole,
       });
       setEmployeeWorkflowData(data);
       const analysis = extractWorkflowAnalysis(data);
       if (analysis.profile) setResumeData({ profile: analysis.profile, extracted_text: text });
       if (analysis.core_gaps || analysis.readiness_score !== undefined) {
         setSkillData({
           readiness_score: analysis.readiness_score,
           core_gaps: analysis.core_gaps || [],
           details: analysis.details?.skill_analysis || {},
         });
       }
       if (analysis.market_gaps || analysis.emerging_skills) {
         setMarketData({
           market_gaps: analysis.market_gaps || [],
           emerging_skills: analysis.emerging_skills || [],
           source_health: analysis.details?.market_analysis?.source_health || {},
           details: analysis.details?.market_analysis || {},
         });
       }
       if (analysis.transition_score !== undefined || analysis.target_role_gaps) {
         setCareerData({
           transition_score: analysis.transition_score,
           target_role_gaps: analysis.target_role_gaps || [],
           details: analysis.details?.career_analysis || {},
         });
       }
       if (analysis.roadmap) setRoadmapData(analysis.roadmap);
     });
   }

  async function runManagerWorkflow() {
    const jd = jobDescription.trim();
    if (!jd) {
      setErrorMessage('Job description is required for manager workflow.');
      return;
    }
    await guarded('workflow', async () => {
      const data = await postJson('/workflow/manager', { job_description: jd });
      setManagerWorkflowData(data);
      if (Array.isArray(data?.matches)) {
        setTalentData({
          status: data.status || 'success',
          matches: data.matches,
          rankings: data.rankings || data.matches,
        });
      }
    });
  }

async function runCompletePipeline() {
     const text = resumeText.trim();
     const selectedTargetRole = targetRole.trim() || currentRole;
     if (!text) {
       setErrorMessage('Resume text is required for complete pipeline.');
       return;
     }
     await guarded('workflow', async () => {
       const data = await postJson('/pipeline/complete', {
         resume_text: text,
         target_role: selectedTargetRole,
       });
       setPipelineData(data);
       const analysis = extractWorkflowAnalysis(data);
       if (analysis.profile) setResumeData({ profile: analysis.profile, extracted_text: text });
       if (analysis.skill_analysis) {
         setSkillData({
           readiness_score: analysis.skill_analysis?.readiness_summary?.readiness_score ?? analysis.readiness_score ?? 0,
           core_gaps: analysis.skill_analysis?.core_gaps || analysis.core_gaps || [],
           skill_gap_json: analysis.skill_analysis,
           details: analysis.skill_analysis,
         });
       }
       if (analysis.career_analysis) {
         setCareerData({
           transition_score: analysis.career_analysis?.feasibility_analysis?.transition_score ?? analysis.transition_score ?? 0,
           target_role_gaps: analysis.career_analysis?.feasibility_analysis?.critical_gaps || analysis.target_role_gaps || [],
           details: analysis.career_analysis,
         });
       }
       if (analysis.learning_roadmap) setRoadmapData(normalizeRoadmapPayload(analysis.learning_roadmap));
     });
   }

  async function runAutopilotJourney() {
    const text = resumeText.trim();
    const selectedTargetRole = targetRole.trim();
    if (!text) {
      setErrorMessage('Resume text is required before running autopilot.');
      return;
    }

    setBusy(true);
    setActiveStage('resume');
    clearError();

    try {
      const resume = await postJson('/analyze/resume', { text });
      setResumeData(resume);
      const role = selectedTargetRole || resume?.profile?.role;
      const liveSkills = sanitizeSkillList(resume?.profile?.skills || []);
      if (!liveSkills.length || !role) {
        throw new Error('Resume extraction did not provide enough profile context to continue.');
      }

      setActiveStage('skill');
      const skill = await postJson('/analyze/skill-gaps', {
        skills: liveSkills,
        role,
        current_role: resume?.profile?.role || role,
        target_role: selectedTargetRole || role,
      });
      setSkillData(skill);

      setActiveStage('market');
      const market = await postJson('/analyze/market-gaps', {
        skills: liveSkills,
        role,
      });
      setMarketData(market);

      setActiveStage('career');
      const career = await postJson('/analyze/transition', {
        profile: { skills: liveSkills, role },
        target_role: selectedTargetRole || role,
      });
      setCareerData(career);

      const liveGaps = mergeGaps(skill, market);
      setActiveStage('learning');
      const roadmap = await postJson('/generate/roadmap', {
        skill_gap: {
          core_gaps: liveGaps,
        profile: { skills: liveSkills, role },
        },
        target_role: selectedTargetRole || role,
      });
      setRoadmapData(roadmap);
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
      setActiveStage('');
    }
  }

  function switchView(nextView) {
    setView(nextView);
    setViewHash(nextView);
  }

  function downloadSkillGapJson() {
    const payload = skillData?.skill_gap_json;
    if (!payload) return;
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'skill_gap.json';
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="si-layout">
      {busy && <LoadingSpinner stage={activeStage} />}
      {showRoleDialog && (
        <RoleSelectionDialog
          open={showRoleDialog}
          suggestions={roleSuggestions}
          onRoleSelect={handleRoleSelect}
          onSkip={() => setShowRoleDialog(false)}
          profileRole={resumeData?.profile?.role}
        />
      )}
      
      <SidebarNav view={view} onViewChange={switchView} />

      <section className="si-main">
        <TopBar
          health={health}
          busy={busy}
          activeStage={activeStage}
          user={currentUser}
          onLogout={handleLogout}
        />

        <section className="kpi-grid">
          <KPI label="Readiness" value={metrics.readiness} hint="Role readiness index" />
          <KPI label="Transition" value={metrics.transition} hint="Career feasibility" />
          <KPI label="Core Gaps" value={metrics.coreGaps} hint="Critical capability gaps" />
          <KPI label="Industry Trending Skills" value={metrics.marketGaps} hint="In-demand industry skills" />
          <KPI label="Roadmap Projects" value={metrics.roadmapProjects} hint="Applied project steps" />
          <KPI label="Talent Matches" value={metrics.matches} hint="Top ranked profiles" />
        </section>

        {successMessage && <SuccessAlert message={successMessage} />}
        {errorMessage && <ErrorAlert message={errorMessage} onDismiss={clearError} />}

        {view === 'overview' ? (
          <section className="view-grid two-col">
            <section className="panel">
              <div className="panel-head panel-head-inline">
                <div>
                  <h3>Welcome back{currentUser?.name ? `, ${currentUser.name.split(' ')[0]}` : ''}</h3>
                  <p className="panel-subtitle">Operational view of workforce readiness and demand</p>
                </div>
                <div className="panel-badge">{new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })}</div>
              </div>
              
              <div className="quick-stats">
                <div className="stat-card">
                  <span className="stat-label">Profile Status</span>
                  <strong className={`stat-value ${needsProfile ? 'stat-warning' : 'stat-success'}`}>
                    {needsProfile ? 'Incomplete' : 'Complete'}
                  </strong>
                </div>
                <div className="stat-card">
                  <span className="stat-label">Current Role</span>
                  <strong className="stat-value">{targetRole.trim() || currentRole || 'Not set'}</strong>
                </div>
                <div className="stat-card">
                  <span className="stat-label">Skills Indexed</span>
                  <strong className="stat-value">{compactNumber(skills.length)}</strong>
                </div>
                <div className="stat-card">
                  <span className="stat-label">Department</span>
                  <strong className="stat-value">{currentUser?.department || '-'}</strong>
                </div>
              </div>

              <div className="panel-head" style={{ marginTop: '24px' }}>
                <h3>Quick Actions</h3>
                <p className="panel-subtitle">Launch a workflow or review operational data</p>
              </div>
              <div className="action-grid">
                <button type="button" className="action-card" onClick={() => switchView('employee')}>
                  <ActionDiagramIcon variant="people" />
                  <div>
                    <strong>Employee Studio</strong>
                    <small>Workforce profile and readiness</small>
                  </div>
                </button>
                <button type="button" className="action-card" onClick={() => switchView('manager')}>
                  <ActionDiagramIcon variant="capacity" />
                  <div>
                    <strong>Manager Console</strong>
                    <small>Capacity planning and role fit</small>
                  </div>
                </button>
                <button type="button" className="action-card" onClick={() => switchView('intelligence')}>
                  <ActionDiagramIcon variant="signals" />
                  <div>
                    <strong>Intelligence Hub</strong>
                    <small>Demand signals and roadmap view</small>
                  </div>
                </button>
                <button type="button" className="action-card" onClick={() => switchView('data')}>
                  <ActionDiagramIcon variant="audit" />
                  <div>
                    <strong>Raw Data</strong>
                    <small>Inspect system payloads</small>
                  </div>
                </button>
              </div>
            </section>

            <section className="panel">
              <div className="panel-head">
                <h3>Pipeline Status</h3>
                <p className="panel-subtitle">Live stage progress and completion state</p>
              </div>
              <div className="pipeline-stages">
                {EXECUTION_STAGES.map((stage) => (
                  <div key={stage} className={`pipeline-stage ${activeStage === stage ? 'active' : ''} ${getStageLabel(stage).toLowerCase().includes('resume') && resumeData ? 'done' : ''} ${getStageLabel(stage).toLowerCase().includes('skill') && skillData ? 'done' : ''} ${getStageLabel(stage).toLowerCase().includes('market') && marketData ? 'done' : ''} ${getStageLabel(stage).toLowerCase().includes('career') && careerData ? 'done' : ''}`}>
                    <span className="stage-indicator" />
                    <div>
                      <span className="stage-name">{getStageLabel(stage)}</span>
                      <small className="stage-status">
                        {activeStage === stage ? 'Running...' : 
                         getStageLabel(stage).toLowerCase().includes('resume') && resumeData ? 'Completed' :
                         getStageLabel(stage).toLowerCase().includes('skill') && skillData ? 'Completed' :
                         getStageLabel(stage).toLowerCase().includes('market') && marketData ? 'Completed' :
                         getStageLabel(stage).toLowerCase().includes('career') && careerData ? 'Completed' :
                         'Pending'}
                      </small>
                    </div>
                  </div>
                ))}
              </div>

              <div className="panel-head" style={{ marginTop: '24px' }}>
                <h3>Top Talent Matches</h3>
                <p className="panel-subtitle">Current ranking snapshot for candidate fit</p>
              </div>
              <TalentPreview talentData={talentData} managerWorkflowData={managerWorkflowData} />
            </section>
          </section>
        ) : null}

        {view === 'employee' ? (
          <section className="view-grid">
            <section className="panel">
              <div className="panel-head"><h3>🎯 Target Role</h3></div>
              <input
                value={targetRole}
                onChange={(event) => setTargetRole(event.target.value)}
                placeholder="e.g., AI Engineer, Cloud Architect, DevOps Engineer"
              />
            </section>

            <section className="panel control-panel file-upload-panel">
              <div className="panel-head"><h3>📄 Upload Resume</h3></div>
              <div className="file-upload-area">
                <input
                  type="file"
                  accept=".txt,.md,.pdf"
                  onChange={(event) => setResumeFile(event.target.files?.[0] || null)}
                  id="resume-file-input"
                />
                <label htmlFor="resume-file-input" className="file-upload-label">
                  <div className="upload-icon">📎</div>
                  <p>{resumeFile ? resumeFile.name : 'Click or drag to upload resume'}</p>
                  <small>Supported: .txt, .md, .pdf</small>
                </label>
              </div>
              <div className="button-row">
                <button type="button" disabled={busy || !resumeFile} onClick={analyzeResumeFile} className="primary-btn">
                  {busy ? '⏳ Analyzing...' : '▶ Analyze File'}
                </button>
                <button type="button" className="secondary" disabled={busy || !resumeFile} onClick={runAutopilotJourney}>
                  🚀 Autopilot Journey
                </button>
              </div>
              {resumeFile && <div className="file-status">✅ File ready: {resumeFile.name}</div>}
            </section>

            <section className="panel control-panel">
              <div className="panel-head"><h3>✏️ Analyze Text</h3></div>
              <label>Paste Resume or Profile Summary</label>
              <textarea
                rows={9}
                value={resumeText}
                onChange={(event) => setResumeText(event.target.value)}
                placeholder="John Doe&#10;Senior Software Engineer&#10;Skills: Java, Python, AWS..."
              />
              <div className="button-row">
                <button type="button" disabled={busy || !resumeText.trim()} onClick={analyzeResumeText}>Analyze Text</button>
                <button type="button" className="secondary" disabled={busy || !resumeText.trim()} onClick={runEmployeeWorkflow}>Employee Workflow</button>
                <button type="button" className="ghost" disabled={busy || !resumeText.trim()} onClick={runCompletePipeline}>Complete Pipeline</button>
              </div>
            </section>

            <section className="panel control-panel">
<div className="panel-head"><h3>⚙️ Run Agents</h3></div>
               <p className="section-hint">Analyze different aspects of the profile in sequence or all at once</p>
               <div className="button-col">
                 <button type="button" disabled={busy || (!targetRole.trim() && !currentRole)} onClick={analyzeSkillGap}>Run Skill Agent</button>
                 <button type="button" disabled={busy || !skills.length} onClick={analyzeMarket}>Run Market Agent</button>
                 <button type="button" disabled={busy || (!targetRole.trim() && !currentRole)} onClick={analyzeCareer}>Run Career Agent</button>
                 <button type="button" disabled={busy || (!targetRole.trim() && !currentRole)} onClick={generateRoadmap}>Run Learning Agent</button>
               </div>
               <div className="agent-note">Requires profile data from resume analysis first</div>
            </section>
          </section>
        ) : null}

        {view === 'resume-output' ? (
          <ResumeProfileView data={resumeData} role={targetRole} />
        ) : null}

        {view === 'skill-output' ? (
          <SkillGapDashboard data={skillData} />
        ) : null}

        {view === 'market-output' ? (
          <MarketIntelligenceView data={marketData} />
        ) : null}

        {view === 'career-output' ? (
          <CareerTransitionView data={careerData} />
        ) : null}

        {view === 'roadmap-output' ? (
          <LearningRoadmapView data={roadmapData} />
        ) : null}

        {view === 'talent-output' ? (
          <TalentMatchesView data={talentData} />
        ) : null}

        {view === 'manager' ? (
          <section className="view-grid two-col">
            <section className="panel control-panel">
              <div className="panel-head"><h3>Demand Intelligence</h3></div>
              <label>Job Description</label>
              <textarea
                rows={10}
                value={jobDescription}
                onChange={(event) => setJobDescription(event.target.value)}
                placeholder="Paste hiring demand, project requirements, and must-have skills"
              />
              <div className="button-row">
                <button type="button" disabled={busy} onClick={matchTalent}>Run Talent Matching</button>
                <button type="button" className="secondary" disabled={busy} onClick={runManagerWorkflow}>Run Manager Workflow</button>
              </div>
            </section>

            <TalentPreview talentData={talentData} managerWorkflowData={managerWorkflowData} />
          </section>
        ) : null}

        {view === 'intelligence' ? (
          <section className="view-grid two-col">
            <RoadmapTimeline roadmapData={roadmapData} />
            <MarketSourceHealth marketData={marketData} />
            <TalentPreview talentData={talentData} managerWorkflowData={managerWorkflowData} />

            <section className="panel">
              <div className="panel-head"><h3>Gap Convergence</h3></div>
              <div className="tag-wrap">
                {allGaps.length
                  ? allGaps.map((gap) => <span className="tag" key={gap}>{gap}</span>)
                  : <span className="tag tag-muted">Run skill and market analysis to build live gap list</span>}
              </div>
            </section>
          </section>
        ) : null}

        {view === 'data' ? (
          <section className="panel-grid">
            <JsonPanel title="Resume Agent Output" data={resumeData} />
            <JsonPanel title="Skill Agent Output" data={skillData} />
            <JsonPanel title="Market Agent Output" data={marketData} />
            <JsonPanel title="Career Agent Output" data={careerData} />
            <JsonPanel title="Learning Agent Output" data={roadmapData} />
            <JsonPanel title="Talent Agent Output" data={talentData} />
            <JsonPanel title="Employee Workflow Output" data={employeeWorkflowData} />
            <JsonPanel title="Manager Workflow Output" data={managerWorkflowData} />
            <JsonPanel title="Complete Pipeline Output" data={pipelineData} />
          </section>
        ) : null}

        {view === 'profile' ? (
          <UserProfileView user={currentUser} />
        ) : null}
      </section>

    </main>
  );
}
