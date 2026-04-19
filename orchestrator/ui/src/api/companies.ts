import type {
  Company,
  CompanyLlmSettings,
  ListLlmModelsQuery,
  TestCompanyLlmSettings,
  UpdateCompanyLlmSettings,
  CompanyPortabilityExportPreviewResult,
  CompanyPortabilityExportResult,
  CompanyPortabilityImportRequest,
  CompanyPortabilityImportResult,
  CompanyPortabilityPreviewRequest,
  CompanyPortabilityPreviewResult,
  UpdateCompanyBranding,
} from "@paperclipai/shared";
import { api } from "./client";

export type CompanyStats = Record<string, { agentCount: number; issueCount: number }>;
export type CompanyLlmSettingsResponse = {
  companyId: string;
  settings: CompanyLlmSettings;
  updatedAt: string;
};
export type LlmProviderDescriptor = {
  id: string;
  label: string;
  requiresBaseUrl: boolean;
  supportsModelListProbe?: boolean;
};
export type LlmModelsProbeResponse = {
  provider: string;
  models: string[];
  status: "ok" | "failed" | "unsupported";
  message?: string;
  details?: unknown;
};
export type CompanyLlmTestResponse = {
  provider: string;
  model: string;
  probe: LlmModelsProbeResponse;
  modelAvailable: boolean | null;
};

export const companiesApi = {
  list: () => api.get<Company[]>("/companies"),
  get: (companyId: string) => api.get<Company>(`/companies/${companyId}`),
  stats: () => api.get<CompanyStats>("/companies/stats"),
  create: (data: {
    name: string;
    description?: string | null;
    budgetMonthlyCents?: number;
  }) =>
    api.post<Company>("/companies", data),
  update: (
    companyId: string,
    data: Partial<
      Pick<
        Company,
        "name" | "description" | "status" | "budgetMonthlyCents" | "requireBoardApprovalForNewAgents" | "brandColor" | "logoAssetId"
      >
    >,
  ) => api.patch<Company>(`/companies/${companyId}`, data),
  updateBranding: (companyId: string, data: UpdateCompanyBranding) =>
    api.patch<Company>(`/companies/${companyId}/branding`, data),
  archive: (companyId: string) => api.post<Company>(`/companies/${companyId}/archive`, {}),
  remove: (companyId: string) => api.delete<{ ok: true }>(`/companies/${companyId}`),
  exportBundle: (
    companyId: string,
    data: {
      include?: { company?: boolean; agents?: boolean; projects?: boolean; issues?: boolean };
      agents?: string[];
      skills?: string[];
      projects?: string[];
      issues?: string[];
      projectIssues?: string[];
      selectedFiles?: string[];
    },
  ) =>
    api.post<CompanyPortabilityExportResult>(`/companies/${companyId}/export`, data),
  exportPreview: (
    companyId: string,
    data: {
      include?: { company?: boolean; agents?: boolean; projects?: boolean; issues?: boolean };
      agents?: string[];
      skills?: string[];
      projects?: string[];
      issues?: string[];
      projectIssues?: string[];
      selectedFiles?: string[];
    },
  ) =>
    api.post<CompanyPortabilityExportPreviewResult>(`/companies/${companyId}/exports/preview`, data),
  exportPackage: (
    companyId: string,
    data: {
      include?: { company?: boolean; agents?: boolean; projects?: boolean; issues?: boolean };
      agents?: string[];
      skills?: string[];
      projects?: string[];
      issues?: string[];
      projectIssues?: string[];
      selectedFiles?: string[];
    },
  ) =>
    api.post<CompanyPortabilityExportResult>(`/companies/${companyId}/exports`, data),
  importPreview: (data: CompanyPortabilityPreviewRequest) =>
    api.post<CompanyPortabilityPreviewResult>("/companies/import/preview", data),
  importBundle: (data: CompanyPortabilityImportRequest) =>
    api.post<CompanyPortabilityImportResult>("/companies/import", data),
  getLlmSettings: (companyId: string) =>
    api.get<CompanyLlmSettingsResponse>(`/companies/${companyId}/llm-settings`),
  updateLlmSettings: (companyId: string, data: UpdateCompanyLlmSettings) =>
    api.put<CompanyLlmSettingsResponse>(`/companies/${companyId}/llm-settings`, data),
  testLlmSettings: (companyId: string, data: TestCompanyLlmSettings) =>
    api.post<CompanyLlmTestResponse>(`/companies/${companyId}/llm-settings/test`, data),
  listLlmProviders: () => api.get<LlmProviderDescriptor[]>("/llm/providers"),
  listLlmModels: (query: ListLlmModelsQuery) => {
    const params = new URLSearchParams();
    params.set("provider", query.provider);
    if (query.base_url) params.set("base_url", query.base_url);
    if (query.api_key) params.set("api_key", query.api_key);
    if (typeof query.timeout_seconds === "number") {
      params.set("timeout_seconds", String(query.timeout_seconds));
    }
    return api.get<LlmModelsProbeResponse>(`/llm/models?${params.toString()}`);
  },
};
