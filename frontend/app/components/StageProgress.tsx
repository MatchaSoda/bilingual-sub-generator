import React from 'react';
import Box from '@mui/material/Box';
import Stepper from '@mui/material/Stepper';
import Step from '@mui/material/Step';
import StepLabel from '@mui/material/StepLabel';

import { PIPELINE_STAGES } from '../../src/automation';

interface StageProgressProps {
  stage?: string | null;
  // 任务面板的状态名：pending / queued / processing / completed / failed / cancelled
  status: string;
  withUpload?: boolean;
  dense?: boolean;
}

// 下载 → 转写 → 翻译 → 压制（→ 投稿）。Web 任务和投稿任务共用，阶段由后端从 entry_cli 的输出推断
const StageProgress = ({ stage, status, withUpload = false, dense = false }: StageProgressProps) => {
  const stages = PIPELINE_STAGES.filter((s) => withUpload || s.key !== 'upload');
  const index = stages.findIndex((s) => s.key === stage);
  const finished = status === 'completed';
  const failed = status === 'failed';
  // 还没开始（排队）时一个都不亮；完成时全部打勾
  const activeStep = finished ? stages.length : index;

  return (
    <Box sx={{ width: '100%' }}>
      <Stepper activeStep={activeStep} alternativeLabel={!dense}>
        {stages.map((s, i) => (
          <Step key={s.key} completed={finished || i < index}>
            <StepLabel
              error={failed && i === index}
              sx={{ '& .MuiStepLabel-label': { fontSize: dense ? 11 : 12, fontWeight: 700, mt: dense ? 0 : 0.5 } }}
            >
              {s.label}
            </StepLabel>
          </Step>
        ))}
      </Stepper>
    </Box>
  );
};

export default StageProgress;
