use alloy::sol;

sol!(
    #[derive(Debug)]
    #[sol(rpc)]
    INonfungiblePositionManager,
    "abi/INonfungiblePositionManager.json"
);

sol!(
    #[derive(Debug)]
    #[sol(rpc)]
    INonfungibleTokenPositionDescription,
    "abi/INonfungibleTokenPositionDescriptor.json"
);

sol!(
    #[derive(Debug)]
    #[sol(rpc)]
    IQuoterV2,
    "abi/IQuoterV2.json"
);

sol!(
    #[derive(Debug)]
    #[sol(rpc)]
    ISwapRouter,
    "abi/ISwapRouter.json"
);

sol!(
    #[derive(Debug)]
    #[sol(rpc)]
    IUniswapV3Factory,
    "abi/IUniswapV3Factory.json"
);

sol!(
    #[derive(Debug)]
    #[sol(rpc)]
    IUniswapV3Pool,
    "abi/IUniswapV3Pool.json"
);