# -*- coding: utf-8 -*-
'''
Expected to have sections which make function calls
'''

''' Imports '''

from helpers import *
from neural_network_module import *
import statsmodels.api as sm

''' Options '''
pd.options.mode.chained_assignment = None
pd.set_option("display.max_columns", 20)
#%%
###############################################################################
## A. Read data and clean
## Data could be Price series OHLCV, Risk Variance series
## 
###############################################################################
options_implied_vol_df = pd.read_csv("../../Data/Options_Implied_Vol.csv")
spx_data_df = pd.read_excel('../../Data/Data_Dump_BBG.xlsx',
                            sheet_name='SPX Index', skiprows=4)
price_history_df = pd.read_excel('../../Data/Data_Dump_BBG.xlsx',
                                 sheet_name='Price History', skiprows=3)
price_history_df.drop(index=[0,1], inplace=True)
price_history_df.rename(columns={price_history_df.columns[0]: 'Dates'},
                                 inplace=True)
price_history_df['Dates'] = pd.to_datetime(price_history_df['Dates'])
bbg_data_df = pd.merge(spx_data_df, price_history_df, on='Dates', how='outer')
options_implied_vol_df = options_implied_vol_data_clean(options_implied_vol_df)
options_implied_vol_df = combine_data(options_implied_vol_df, bbg_data_df)
#fridays_list = list(options_implied_vol_df.resample('W-Fri',
#                                                    on='date')['date'].last())
spx_data = spx_data_df[['Dates', 'PX_LAST']]
spx_data['PX_LAST'].fillna(method='ffill', inplace=True)
spx_data.rename(columns={'PX_LAST':'SPX'}, inplace=True)
spx_data["Dates"] =  pd.to_datetime(spx_data["Dates"])
spx_data["Returns"] = spx_data["SPX"].pct_change()
spx_data['Log_Returns'] = spx_data[['SPX']].apply(lambda x: np.log(x/x.shift(1)))
spx_data.dropna(inplace=True)
spx_data["Std Dev"] = spx_data["Returns"].rolling(5).std()
spx_data['Variance'] = spx_data['Std Dev']**2
returns_series = spx_data["Returns"]
cum_mean_returns = returns_series.cumsum()/np.arange(1, len(returns_series)+1)
spx_data['Innovations'] = returns_series - cum_mean_returns
spx_data["Innovations_Squared"] = spx_data['Innovations']**2
regression_df = spx_data.resample('W-Fri', on='Dates').last()
regression_df.dropna(inplace=True)
y = regression_df['Variance'].values[1:]
X = regression_df[['Variance', 'Innovations_Squared']].values[:-1]
#%%
###############################################################################
## B. Variance Series Smoothing, and Baselining
###############################################################################
X = sm.add_constant(X)
num_points = y.size
train_idx = int(num_points*0.6)
cv_idx = int(num_points*0.85)
X_train, y_train = X[:train_idx], y[:train_idx]
X_cv, y_cv = X[train_idx:cv_idx], y[train_idx:cv_idx]
X_test, y_test = X[cv_idx:], y[cv_idx:]
dates = regression_df['Dates'][1:]

###############################################################################
# B.1. Benchmark calculations
###############################################################################
garch_result = sm.OLS(y_train, X_train).fit()
garch_params = garch_result.params
#Forecast on the cv set using the fitted parameters
#Take square root to convert variances to vol
y_cv_benchmark = np.sqrt(X_cv @ garch_params)
y_train_benchmark = np.sqrt(X_train @ garch_params)

###############################################################################
# B.2. Naive calculations
###############################################################################
#Forecast using the naive model
y_cv_naive = np.mean(np.sqrt(y_train))

###############################################################################
# B.3. Neural Network calculations
###############################################################################
#Fit NN to training data
stddev_window = 5
#lag_innov = np.sqrt(X[:, 1])
lag_innov = np.stack((np.sqrt(X[:, 1]), X[:, 2])).T
lag_innov = np.column_stack((lag_innov,
                             regression_df['Innovations'].values[:-1]))
num_nn_inputs = lag_innov.shape[1]
innov = np.sqrt(y)
jnn_trained, nn_fit_vol, nn_forecast_vol, _ = run_jnn(lag_innov, innov,
                                                      stddev_window,
                                                      train_idx, cv_idx,
                                                      batch_size=256,
                                                      epochs=1000,
                                                      plot_flag=False,
                                                      jnn_size=(num_nn_inputs,
                                                                1, 1))
jnn_weights = jnn_trained.get_weights()
# Plot Benchmark against Realized Vol for trained series
train_dates = dates[:train_idx]
y_train_true = regression_df.loc[regression_df["Dates"].isin(train_dates),
                                 "Std Dev"].values
plt.plot(train_dates, y_train_true, label = "Realized Volatilty")
plt.plot(train_dates, y_train_benchmark, label = "GARCH (benchmark)")
plt.plot(train_dates, nn_fit_vol, label = "Latest State of the Art",
         marker='_', color='moccasin')
plt.legend()
plt.grid(True)
plt.xticks(rotation=90.)
plt.title("Realized vs GARCH vs State of the Art (Fitted)")
plt.savefig("../Results/Fitted_Comparison_Vol.jpg")

# Plot forecast window ahead Benchmark and NN volatility against Realized Vol
# for cv set
forecast_dates = dates[train_idx:cv_idx]
y_cv_true = regression_df.loc[regression_df["Dates"].isin(forecast_dates),
                              "Std Dev"].values
plt.clf()
plt.rcParams["figure.figsize"] = (15,10)
plt.plot(forecast_dates, y_cv_true, label = "Realized Volatilty")
plt.plot(forecast_dates, y_cv_benchmark, label = "GARCH (benchmark)",
         marker='.')
plt.plot(forecast_dates, nn_forecast_vol, label = "Latest State of the Art",
         marker='_', color='moccasin')
plt.legend()
plt.grid(True)
plt.xticks(rotation=30.)
plt.title("Realized vs GARCH vs State of the Art")
plt.savefig("../Results/Forecast_Comparison_Vol.jpg")

# Calculate Benchmark Values on the CV set (against volatility)
garch_cv_mse = np.mean((y_cv_benchmark - y_cv_true)**2)
print('The Benchmark MSE on the cv is {:.2e}'.format(garch_cv_mse))

# Calculate NN Values on the CV set (against volatility)
nn_cv_mse = np.mean((y_cv_true - nn_forecast_vol)**2)
print('The NN MSE on the cv is {:.2e}'.format(nn_cv_mse))

# Calculate Naive Values on the CV set (against volatility)
naive_cv_mse = np.mean((y_cv_true - y_cv_naive)**2)
print('The Naive MSE on the cv is {:.2e}'.format(naive_cv_mse))

# Calculate the forecast df
forecast_df = pd.DataFrame(y_cv_benchmark, forecast_dates, ['Forecast_Vol'])

# Calculate the realized df
realized_df = pd.DataFrame(y_cv_true, forecast_dates, ['Forecast_Vol'])

# Calculate the NN forecast df
nn_forecast_df = pd.DataFrame(nn_forecast_vol, forecast_dates,
                              ['Forecast_Vol'])
#%%
# Backtest the benchmark
benchmark_df = backtester(forecast_df, options_implied_vol_df,
                          'GARCH Back Test', look_ahead=7, atm_only=True)
benchmark_df.to_csv('GARCH Performance.csv')
#%%
# Backtest the realized vol
best_case_df = backtester(realized_df, options_implied_vol_df,
                          'Realized Back Test', look_ahead=7, atm_only=True,
                          trade_expiry=True)
best_case_df.to_csv('Realized Performance.csv')
#%%
# Backtest the Neural Net
nn_df = backtester(nn_forecast_df, options_implied_vol_df,
                   'Neural Net Back Test', look_ahead=7, atm_only=True)
nn_df.to_csv('NN Performance.csv')
#%%
###############################################################################
## C. Feature Creation
##
###############################################################################


###############################################
## C. Feature Creation
## a. Technical Data Creation
###############################################


###############################################
## C. Feature Creation
## b. NLP Data Feature Creation
###############################################


###############################################
## C. Feature Creation
## c. NLP Data Feature Creation
###############################################

###############################################################################
## Z. APPENDIX
## I. Trends Scraping
###############################################################################
positive_words = ["gainer","whistleblower","speedy","dubious","scraps",
                  "acknowledge","delisted","downs","boding","disappeared",
                  "botched","kongs","surely","resurgent","eos","hindered",
                  "leapt","grapple","heated","forthcoming","standpoint",
                  "exacerbated","steer","toptier","braking","jackets",
                  "featured","overcrowded","saddled","haul"
                  ]

negative_words = ["dating","birthrate","reacting","lofty","accelerators",
                  "falsified","bust","averaging","pages","championed",
                  "folded","trillions","santa","fourfold","wellknown",
                  "perfect","defaults","bottleneck","cloudy",
                  "strains","kicks","doubted","halving","retailing","abandon",
                  "depressing","specifications","businessmen","diluting"
                  ]

scrape_these_words(key_words =positive_words ,path = "../data",
                       file_name = "positive_words_2000.csv")

scrape_these_words(key_words =negative_words ,path = "../data",
                       file_name = "negative_words_2000.csv")
