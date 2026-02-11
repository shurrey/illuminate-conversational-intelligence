/**
 * ExportButton - Export data to various formats.
 */

import { useState } from 'react';
import type { Artifact } from '../../types/message';

interface ExportButtonProps {
  artifacts: Artifact[];
  className?: string;
}

export function ExportButton({ artifacts, className = '' }: ExportButtonProps) {
  const [isOpen, setIsOpen] = useState(false);

  const exportableArtifacts = artifacts.filter(
    a => a.type === 'table' || a.type === 'chart'
  );

  if (exportableArtifacts.length === 0) {
    return null;
  }

  const exportToCSV = () => {
    exportableArtifacts.forEach(artifact => {
      if (artifact.type === 'table') {
        const data = artifact.data as { rows: Record<string, unknown>[]; columns: string[] };
        const columns = data.columns || Object.keys(data.rows[0] || {});

        // Build CSV content
        const header = columns.join(',');
        const rows = data.rows.map(row =>
          columns.map(col => {
            const val = row[col];
            if (typeof val === 'string' && (val.includes(',') || val.includes('"'))) {
              return `"${val.replace(/"/g, '""')}"`;
            }
            return val;
          }).join(',')
        );

        const csv = [header, ...rows].join('\n');
        downloadFile(csv, `${artifact.title || 'data'}.csv`, 'text/csv');
      }
    });

    setIsOpen(false);
  };

  const exportToJSON = () => {
    const data = exportableArtifacts.map(artifact => ({
      title: artifact.title,
      type: artifact.type,
      data: artifact.data
    }));

    downloadFile(
      JSON.stringify(data, null, 2),
      'export.json',
      'application/json'
    );

    setIsOpen(false);
  };

  const copyToClipboard = async () => {
    const tableArtifacts = exportableArtifacts.filter(a => a.type === 'table');

    if (tableArtifacts.length > 0) {
      const data = tableArtifacts[0].data as { rows: Record<string, unknown>[]; columns: string[] };
      const columns = data.columns || Object.keys(data.rows[0] || {});

      // Build tab-separated values for pasting into spreadsheets
      const header = columns.join('\t');
      const rows = data.rows.map(row =>
        columns.map(col => row[col] ?? '').join('\t')
      );

      const tsv = [header, ...rows].join('\n');

      try {
        await navigator.clipboard.writeText(tsv);
        // Could show a toast here
      } catch (err) {
        console.error('Failed to copy:', err);
      }
    }

    setIsOpen(false);
  };

  return (
    <div className={`relative ${className}`}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-600 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
          />
        </svg>
        Export
      </button>

      {isOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-10"
            onClick={() => setIsOpen(false)}
          />

          {/* Dropdown */}
          <div className="absolute right-0 mt-1 w-40 bg-white rounded-md shadow-lg border border-gray-200 z-20">
            <div className="py-1">
              <button
                onClick={exportToCSV}
                className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-100"
              >
                Download CSV
              </button>
              <button
                onClick={exportToJSON}
                className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-100"
              >
                Download JSON
              </button>
              <button
                onClick={copyToClipboard}
                className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-100"
              >
                Copy to Clipboard
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function downloadFile(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default ExportButton;
