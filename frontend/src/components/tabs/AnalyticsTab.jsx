import React from 'react';
import LearningDashboard from '../LearningDashboard';
import { Card } from '../shared/UIComponents';

const AnalyticsTab = () => {
  return (
    <div className="space-y-4 mt-2" data-testid="analytics-tab-content">
      <Card>
        <LearningDashboard />
      </Card>
    </div>
  );
};

export default AnalyticsTab;
