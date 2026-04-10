import {
  registerAppResource,
  registerAppTool,
  RESOURCE_MIME_TYPE,
} from "@modelcontextprotocol/ext-apps/server";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type {
  CallToolResult,
  ReadResourceResult,
} from "@modelcontextprotocol/sdk/types.js";
import fs from "node:fs/promises";
import path from "node:path";
import { z } from "zod";

const DIST_DIR = import.meta.filename.endsWith(".ts")
  ? path.join(import.meta.dirname, "dist")
  : import.meta.dirname;

const questionTemplate = {
  mandatory: [
    {
      id: "requestFor",
      text: "Add Other Users",
      mandatory: false,
      type: "user-search",
    },
    {
      id: "analysisDateRange",
      text: "Analysis Start and End Date",
      mandatory: true,
      type: "dateRange",
    },
    {
      id: "proposalName",
      text: "What is the Proposal Name?",
      mandatory: true,
      type: "text",
      validation: { minLength: 3, maxLength: 200 },
    },
    {
      id: "scientificPurpose",
      text: "Scientific Purpose of the Request",
      mandatory: true,
      type: "textarea",
      validation: { minLength: 10 },
    },
    {
      id: "scopeActivity",
      text: "Scope of the activity",
      mandatory: true,
      type: "textarea",
      validation: { minLength: 10 },
    },
  ],
  ddf: [
    {
      id: "userIHDActivity",
      text: "Who will perform the IHD activity?",
      mandatory: true,
      type: "multiSelect",
      options: ["Internal", "External by a third party"],
    },
    {
      id: "roles",
      text: "Roles and responsibilities of those involved",
      mandatory: true,
      type: "textarea",
      validation: { minLength: 10 },
    },
    {
      id: "typeActivity",
      text: "Types of IHD source this request includes",
      mandatory: true,
      type: "multiSelect",
      options: [
        {
          text: "GSK IHD Sources",
          info: "<p>Includes:</p><ul><li>Ongoing GSK-sponsored clinical studies where IHD activity is out of scope of the original protocol</li><li>Completed GSK-sponsored clinical studies</li><li>Ongoing or completed Supported Collaborative Studies (SCS) or Investigator Sponsored Studies (ISS)</li><li>Studies acquired through in-licensing or company acquisitions</li><li>Pharmacovigilance data</li></ul>",
        },
        {
          text: "External",
          info: "<ul><li>Publicly available IHD</li><li>Third-party IHD</li></ul>",
        },
      ],
    },
    {
      id: "versionICF",
      text: "Version of protocol / Version of ICF",
      mandatory: true,
      type: "textarea",
      validation: { minLength: 10 },
      info: "<p>Please include the latest version number for the study protocol or ICF.</p>",
    },
    {
      id: "sectionICF",
      text: "Section of protocol / Section of ICF",
      mandatory: true,
      type: "textarea",
      validation: { minLength: 10 },
      info: "<p>Please include the section of the study protocol or ICF that the proposed activity relates to.</p>",
    },
    {
      id: "utilized",
      text: "Can anonymized data be utilized for your analysis?",
      mandatory: true,
      type: "select",
      options: ["Yes", "No"],
      allowOther: true,
      info: '<p><strong>Anonymization</strong> refers to the processing of personal information (PI) so that individuals cannot be identified by any reasonable means.</p><p>For most research purposes, anonymization has minimal impact on data usability. Variables such as demographics, clinical events, and observed values are retained; free text is removed. Identifiers such as subject IDs, visit dates, and site/investigator details are transformed.</p><p>Approved reuse of anonymized data may be subject to country-level restrictions (e.g., exclusion of subjects from countries where anonymization standards are not met).</p>',
    },
    {
      id: "regulated",
      text: "Is this a regulatory request?",
      mandatory: true,
      type: "select",
      options: ["Yes", "No"],
      info: "<ul><li>Regulatory requests</li><li>Safety requests for DSUR or PSUR generation</li><li>Reimbursement requests</li></ul>",
    },
    {
      id: "evaluation",
      text: "Is evaluation related to a GSK product?",
      mandatory: true,
      type: "select",
      options: ["Yes", "No"],
    },
    {
      id: "completeSubset",
      text: "Is this request for complete study data or a subset?",
      mandatory: true,
      type: "select",
      options: ["Complete", "Subset"],
      info: "<p>Select <strong>Complete</strong> if you require all available study data.</p><p>Select <strong>Subset</strong> if you require specific parts only (e.g., efficacy, safety, selected countries).</p>",
    },
    {
      id: "purposeCriteria",
      text: "If your request includes GSK IHD sources, please select which criteria apply to the purpose of the requested IHD",
      mandatory: true,
      type: "multiSelect",
      options: [
        "Carry out this study and meet the study purpose",
        "Understand the results of this study",
        "Bring the study drug/vaccine to market and support reimbursement",
        "Satisfy regulatory requirements",
        "Develop diagnostic tests to support use of the study drug/vaccine",
        "Ensure the quality of the tests used for the study",
        "Ensure the quality of the tests used for the study drug/vaccine or disease is maintained over time",
        "Develop and improve tests related to the study drug/vaccine or disease",
        "Design additional studies relating to the study drug/vaccine, study disease and related conditions",
        "Support clinical study processes",
        "Publish results of the study",
        "Foster clinical trial diversity in ethnic groups",
        "My request includes GSK IHD sources, but none of the above criteria apply",
        "My request includes GSK IHD sources, but I am not sure if any of the above criteria apply",
        "My request only includes external IHD sources",
      ],
    },
    {
      id: "legitimatePurpose",
      text: "Specific and legitimate purpose of the activity",
      mandatory: true,
      type: "textarea",
      validation: { minLength: 10 },
      info: "<p>For regulatory, safety, or reimbursement-related requests, provide details on the specific regulatory body, safety report, or reimbursement purpose.</p>",
    },
    {
      id: "activityType",
      text: "Type of activity to be performed",
      mandatory: true,
      type: "textarea",
      validation: { minLength: 10 },
    },
    {
      id: "dataDescription",
      text: "Broad description of the data to be used and rationale where anonymized IHD cannot be used",
      mandatory: true,
      type: "textarea",
      validation: { minLength: 10 },
    },
    {
      id: "linksToPlan",
      text: "Links to other plans (e.g., asset plans, publication plans)",
      mandatory: true,
      type: "text",
    },
    {
      id: "reporting",
      text: "Details on reporting, disclosure, and close-out activities required",
      mandatory: true,
      type: "textarea",
      info: "<p>Include the final intent of the IHD activity, long-term data management and retention needs, storage location (internal or third party), and how access will be restricted for future reuse.</p>",
    },
    {
      id: "futureReuse",
      text: "Considerations for future data re-use",
      mandatory: true,
      type: "textarea",
      validation: { minLength: 10 },
    },
    {
      id: "useReuseCategory",
      text: "Is the request for use or reuse?",
      mandatory: true,
      type: "select",
      options: [
        "Study Use",
        "Further Use Related",
        "Further Use Not Related",
      ],
      info: "<p><strong>Study Use</strong>: Primary use as defined in the study protocol or ICF.</p><p><strong>Further Use Related</strong>: Secondary use by participants who consented to further research related to the study drug/vaccine or disease.</p><p><strong>Further Use Not Related</strong>: Secondary use by participants who consented to research unrelated to the original study objectives.</p>",
    },
  ],
  default: [
    {
      id: "ihdActivityProposalText",
      text: "Completed IHD Activity Proposal (Text)",
      mandatory: true,
      type: "textarea",
      validation: { minLength: 10 },
    },
    {
      id: "ihdActivityProposalFile",
      text: "Completed IHD Activity Proposal (File)",
      mandatory: false,
      type: "file",
      fileTypes: ["docx"],
      maxFiles: 1,
      maxFileSizeMB: 10,
    },
  ],
  onyx: [
    {
      id: "userIHDActivity",
      text: "Who will perform the IHD activity?",
      mandatory: true,
      type: "multiSelect",
      options: ["Internal", "External by a third party"],
    },
  ],
  productSpecific: {},
};

export function createServer(): McpServer {
  const server = new McpServer({
    name: "Question Form App Server",
    version: "1.0.0",
  });

  const resourceUri = "ui://question-form/mcp-app.html";

  registerAppTool(
    server,
    "open-question-form",
    {
      title: "Question Form",
      description:
        "Opens an interactive question form with multiple sections (Mandatory, DDF, Default, Onyx). Each section contains fields with appropriate controls like text inputs, textareas, date pickers, dropdowns, multi-selects, and file uploads. Fields are validated according to their configuration.",
      inputSchema: {
        section: z
          .enum(["all", "mandatory", "ddf", "default", "onyx"])
          .optional()
          .describe(
            "Which section to display. Defaults to 'all' to show all sections.",
          ),
      },
      _meta: { ui: { resourceUri } },
    },
    async (args): Promise<CallToolResult> => {
      const section = (args.section as string) ?? "all";
      let templateData: Record<string, unknown>;

      if (section === "all") {
        templateData = questionTemplate;
      } else {
        templateData = {
          [section]:
            questionTemplate[section as keyof typeof questionTemplate],
        };
      }

      const sectionNames = Object.keys(templateData);
      const totalFields = sectionNames.reduce((sum, key) => {
        const val = templateData[key];
        return sum + (Array.isArray(val) ? val.length : 0);
      }, 0);

      return {
        content: [
          {
            type: "text",
            text: `Question form loaded with ${sectionNames.length} section(s) and ${totalFields} field(s). Sections: ${sectionNames.join(", ")}`,
          },
        ],
        structuredContent: {
          template: templateData,
          section,
        },
      };
    },
  );

  registerAppResource(
    server,
    resourceUri,
    resourceUri,
    { mimeType: RESOURCE_MIME_TYPE },
    async (): Promise<ReadResourceResult> => {
      const html = await fs.readFile(
        path.join(DIST_DIR, "mcp-app.html"),
        "utf-8",
      );
      return {
        contents: [{ uri: resourceUri, mimeType: RESOURCE_MIME_TYPE, text: html }],
      };
    },
  );

  return server;
}
