
def get_cscore_opm(ratio):
	score = 0
	if ratio > 20 :
		# excellent
		score = 4
	elif ratio > 15 and ratio <= 20:
		# good
		score = 3
	elif ratio > 10 and ratio <= 15:
		# average
		score = 2
	elif ratio > 5 and ratio <= 10:
		# good 
		score = 1
	elif ratio < 5:
		# very poor
		score = 0 
	return score

def get_cscore_dp(ratio):
	score = 0
	if ratio > 20 :
		# excellent
		score = 4
	elif ratio > 15 and ratio <= 20:
		# good
		score = 3
	elif ratio > 10 and ratio <= 15:
		# average
		score = 2
	elif ratio > 5 and ratio <= 10:
		# good 
		score = 1
	elif ratio < 5:
		# very poor
		score = 0 
	return score

# Analyst prefer interest coverage ratio above 3
def get_cscore_ic(ratio):
	if ratio >= 3:
		# good : preferred by analyst
		score = 100 + ratio
	elif ratio >= 2:
		# minimum acceptable value
		score = 2
	elif ratio >= 1:
		score = 1
	elif ratio < 1:
		score = -100 
	return score

# debt to equity
# Analysst prefer : 25% debt and 75% equity
# difficult for bank and nbfc
# we should check if equity is also increasing in line with debt through balance
# sheet
def get_cscore_d2e(ratio):
	# For Bank and NBFC : debt to equity can be high.
	if ratio == 0:
		# best
		score = 100 
	elif ratio > 0 and ratio <= 0.25 :
		# wonderful
		score = 50 
	elif ratio > 0.25 and ratio <= 1 :
		# good 
		score = 25
	elif ratio > 1 and ratio <=2 :
		# poor 
		score = 1
	elif ratio > 2 and ratio < 5:
		# waste 
		score = -ratio 
	elif ratio >= 5:
		# waste 
		score = 0 - ratio
		score = score - 100
	elif ratio < 0:
		# Raise an alert for this.
		# waste  (negative : renuka sugars)
		score = 0
	return score

def get_cscore_altmanz(ratio):
	# Is the number different for bank & nbfc - finance?
	if ratio <= 2:
		# chance of bankruptcy
		score = -4 
	elif ratio > 2 and ratio <= 3:
		score = 0 
	elif ratio > 3: 
		# sound - healthy company 
		score = 4 
	return score

def get_cscore_current_ratio(ratio):
	if ratio > 3: 
		# better 
		score = 3
	elif ratio >= 1.5 and ratio <= 3:
		# ideal
		score = 2
	elif ratio >= 1 and ratio < 1.5 :
		# less than ideal 
		score = 1
	elif ratio < 1 :
		# not enough cash
		score = 0
	return score

def get_cscore_pledge(ratio):
	score = 0
	if ratio >= 50 :
		# worst 
		score = 0
	elif ratio >= 25 :
		# poor 
		score = 1
	elif ratio >= 10 :
		#  averge
		score = 2
	elif ratio > 1 and ratio < 10 :
		#  good 
		score = 3
	elif ratio == 0 :
		#  best 
		score = 4
	return score
