import { createContext, useContext } from 'react';

const TrainCommandContext = createContext(null);

export const TrainCommandProvider = TrainCommandContext.Provider;

export const useTrainCommand = () => useContext(TrainCommandContext);
