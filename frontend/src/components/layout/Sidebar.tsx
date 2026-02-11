/**
 * Sidebar - Data information and navigation.
 *
 * Currently focused on CDM_LMS (Blackboard Learn) data only.
 */


interface SidebarProps {
  onClose: () => void;
}

export function Sidebar({ onClose }: SidebarProps) {
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-gray-200">
        <h2 className="font-semibold text-gray-900">Data Source</h2>
        <button
          onClick={onClose}
          className="p-1 lg:hidden hover:bg-gray-100 rounded-md"
          aria-label="Close sidebar"
        >
          <svg className="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Data source info */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="bg-blue-50 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <div className="text-blue-600">
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
              </svg>
            </div>
            <div>
              <div className="font-medium text-blue-900">Blackboard Learn</div>
              <div className="text-sm text-blue-700 mt-1">CDM_LMS Schema</div>
            </div>
          </div>
        </div>

        {/* Available data types */}
        <div className="mt-6">
          <h3 className="text-sm font-medium text-gray-700 mb-3">Available Data</h3>
          <ul className="space-y-2 text-sm text-gray-600">
            <li className="flex items-center gap-2">
              <span className="w-2 h-2 bg-green-500 rounded-full"></span>
              Courses & sections
            </li>
            <li className="flex items-center gap-2">
              <span className="w-2 h-2 bg-green-500 rounded-full"></span>
              Student enrollments
            </li>
            <li className="flex items-center gap-2">
              <span className="w-2 h-2 bg-green-500 rounded-full"></span>
              Grades & assignments
            </li>
            <li className="flex items-center gap-2">
              <span className="w-2 h-2 bg-green-500 rounded-full"></span>
              Academic terms
            </li>
          </ul>
        </div>

        {/* Example queries */}
        <div className="mt-6">
          <h3 className="text-sm font-medium text-gray-700 mb-3">Try asking</h3>
          <ul className="space-y-2 text-sm text-gray-500">
            <li>"What is the average GPA?"</li>
            <li>"How many courses are there?"</li>
            <li>"Show enrollment by department"</li>
            <li>"Which courses have the highest grades?"</li>
          </ul>
        </div>
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-gray-200">
        <div className="text-xs text-gray-500">
          <p className="font-medium mb-1">Data Refresh</p>
          <p>CDM_LMS updates overnight</p>
        </div>
      </div>
    </div>
  );
}

export default Sidebar;
