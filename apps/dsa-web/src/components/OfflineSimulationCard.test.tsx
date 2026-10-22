import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import OfflineSimulationCard from './OfflineSimulationCard';

const { runOfflineSimulation } = vi.hoisted(() => ({ runOfflineSimulation: vi.fn() }));

vi.mock('../api/operations', () => ({
  operationsApi: { runOfflineSimulation },
}));

beforeEach(() => {
  vi.clearAllMocks();
  runOfflineSimulation.mockResolvedValue({
    scenario_id: 'scenario-1',
    environment: 'LOCAL_OFFLINE_SIMULATION',
    symbol: 'TSLA',
    side: 'BUY',
    quantity: '1',
    limit_price: '100',
    currency: 'USD',
    runtime_state: 'READY',
    order_state: 'FILLED',
    filled_quantity: '1',
    external_fill_confirmation: false,
    fill_source: 'LOCAL_SCENARIO_FIXTURE',
    broker_io: false,
    provider_io: false,
    live_trade: false,
    note: 'Local fixture only',
  });
});

describe('OfflineSimulationCard', () => {
  it('submits only after user action and labels the local fixture result', async () => {
    render(<OfflineSimulationCard />);
    expect(runOfflineSimulation).not.toHaveBeenCalled();

    fireEvent.submit(document.querySelector('form')!);

    expect(await screen.findByRole('status')).toBeInTheDocument();
    expect(runOfflineSimulation).toHaveBeenCalledWith({
      symbol: 'TSLA', side: 'BUY', quantity: '1', limit_price: '100', simulate_fill: false,
    });
  });
});
