/**
 * DataTable - Renders tabular data with sorting.
 */

import { useState, useMemo } from 'react';

interface TableData {
  rows: Record<string, unknown>[];
  columns: string[];
}

interface DataTableProps {
  data: TableData;
  maxRows?: number;
  className?: string;
}

type SortDirection = 'asc' | 'desc' | null;

export function DataTable({
  data,
  maxRows = 10,
  className = ''
}: DataTableProps) {
  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>(null);
  const [showAll, setShowAll] = useState(false);

  const columns = data.columns || (data.rows.length > 0 ? Object.keys(data.rows[0]) : []);

  const sortedRows = useMemo(() => {
    if (!sortColumn || !sortDirection) {
      return data.rows;
    }

    return [...data.rows].sort((a, b) => {
      const aVal = a[sortColumn];
      const bVal = b[sortColumn];

      if (aVal === bVal) return 0;
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;

      const comparison = aVal < bVal ? -1 : 1;
      return sortDirection === 'asc' ? comparison : -comparison;
    });
  }, [data.rows, sortColumn, sortDirection]);

  const displayedRows = showAll ? sortedRows : sortedRows.slice(0, maxRows);
  const hasMore = sortedRows.length > maxRows;

  const handleSort = (column: string) => {
    if (sortColumn === column) {
      setSortDirection(prev =>
        prev === 'asc' ? 'desc' : prev === 'desc' ? null : 'asc'
      );
      if (sortDirection === 'desc') {
        setSortColumn(null);
      }
    } else {
      setSortColumn(column);
      setSortDirection('asc');
    }
  };

  const formatValue = (value: unknown): string => {
    if (value === null || value === undefined) return '-';
    if (typeof value === 'number') {
      return Number.isInteger(value) ? value.toString() : value.toFixed(2);
    }
    return String(value);
  };

  if (data.rows.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500 text-sm">
        No data available
      </div>
    );
  }

  return (
    <div className={`overflow-x-auto ${className}`}>
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            {columns.map(column => (
              <th
                key={column}
                onClick={() => handleSort(column)}
                className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 select-none"
              >
                <div className="flex items-center gap-1">
                  {column}
                  <SortIcon
                    active={sortColumn === column}
                    direction={sortColumn === column ? sortDirection : null}
                  />
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {displayedRows.map((row, rowIndex) => (
            <tr
              key={rowIndex}
              className="hover:bg-gray-50 transition-colors"
            >
              {columns.map(column => (
                <td
                  key={column}
                  className="px-4 py-3 text-sm text-gray-900 whitespace-nowrap"
                >
                  {formatValue(row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      {/* Show more/less */}
      {hasMore && (
        <div className="py-2 px-4 bg-gray-50 border-t border-gray-200">
          <button
            onClick={() => setShowAll(!showAll)}
            className="text-sm text-blue-600 hover:text-blue-700"
          >
            {showAll
              ? 'Show less'
              : `Show all ${sortedRows.length} rows`}
          </button>
        </div>
      )}
    </div>
  );
}

interface SortIconProps {
  active: boolean;
  direction: SortDirection;
}

function SortIcon({ active, direction }: SortIconProps) {
  return (
    <svg
      className={`w-4 h-4 ${active ? 'text-blue-600' : 'text-gray-400'}`}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      {direction === 'asc' ? (
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
      ) : direction === 'desc' ? (
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
      ) : (
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
      )}
    </svg>
  );
}

export default DataTable;
